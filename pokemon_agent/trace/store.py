"""`MockTrace` —— `TracePort` 的实现，把事件堆在内存列表里，顺手推流到控制台。

**它是 mock 存储**（内存列表、进程一退就没了），但 `TracePort` 的三个方法它都
**真的实现**，不是占位：`append` 持久化 + 分配单调 event_id，`replay` 按
episode 过滤重放，`sse` 推流——**现在打印到控制台，以后是推给浏览器的连接**，
调用点不变，换的只是 `sse()` 这一个方法内部的实现（见 `interfaces/trace.py`）。

以前这两件事分在两个文件、两层对象里：`mocks/mock_trace.py` 只管存储，
`probe/echo_trace.py` 是包住它的一个装饰器，专门负责打印。拆开是因为当时
`TracePort` 协议里没有"推流"这个位置——`EchoTrace` 只能从外面在 `append` 上
加一层旁路。现在协议本身有了 `sse()`，打印就是这个方法**应该长的样子**，
不再需要外面再包一层装饰器；换成推浏览器时，也只需要换一个实现了
`TracePort` 的类，`append`/`replay` 的代码一行不用抄。

真正落盘、按失败类型聚合统计——这些还没做，那是阶段 2 的事。
"""

from __future__ import annotations

import json
import textwrap
import time
from collections.abc import Iterable

from pokemon_agent.schemas.trace import EventType, Source, TraceEvent

LABEL_W = 15
"""标签列宽。

由最长的标签 `perception_cost` 决定。写成常量而不是散在各处的 `:<9`，
是因为对齐一旦不一致，多行的 `thought` 会和单行的 `action` 错开——
读日志的人第一眼看到的就是排版乱，而不是内容。
"""

COST_LABEL: dict[Source, str] = {
    Source.PERCEPTION: "perception_cost",
    Source.DECISION: "decision_cost",
    Source.JUDGE: "judge_cost",
}
"""MODEL_CALL 事件的标签。

**要带 `_cost`**：那一行报的是 token 和延迟，是**这次调用花了多少**，
不是"感知到了什么"。光写 `perception` 会和下面的 `observe` 混成一件事，
而它们一个是账单一个是内容。
"""


class MockTrace:
    """事件的追加、回放与推送。没有删除和修改，这是刻意的。"""

    def __init__(self, run_id: str = "local") -> None:
        """`run_id` 在构造时定：一次实验一个 trace 实例，每条事件都属于它。"""
        self._run_id = run_id
        self._events: list[TraceEvent] = []
        self._next_id = 0
        self._step_shown: tuple[str, int] | None = None
        """这一步的表头打过没有，`sse()` 用。

        表头是 **step 的标题**，不是某个事件的标题，所以由步号变化触发，
        而不是挂在某个特定 `EventType` 上——挂在 `OBSERVE` 上是不行的：
        事件流里 `MODEL_CALL(perception)` 在它前面（因果顺序，产出观测的调用
        当然更早），表头就会打在本步的成本行下面，看日志的人把那行成本
        读成上一步的。排版问题在这里解决，**不去改事件流**——trace 是唯一的
        事实来源。
        """

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id，随后推给 `sse()`。

        前置条件：step >= 0、episode_id 非空。
        后置条件：返回值严格大于此前任何一次 append 的返回值。
            SSE 的断线补发完全依赖这条，一旦重复或回退，观测台会静默丢事件。
        """
        assert step >= 0, f"step must be >= 0, got {step}"
        assert episode_id, "append() got an empty episode_id"

        event_id = self._next_id
        self._next_id += 1

        event = TraceEvent(
            event_id=event_id,
            run_id=self._run_id,
            episode_id=episode_id,
            step=step,
            type=type,
            source=source,
            payload=payload or {},
            # ts 由实现方填：时间戳是 trace 的属性，不是业务参数。
            ts=time.time(),
        )
        self._events.append(event)

        assert not self._events[:-1] or event_id > self._events[-2].event_id, (
            "event_id must be strictly increasing"
        )
        # **落盘之后立刻推**——推流的事件和落盘的事件是同一条，
        # 不能有第二个源头（见 `interfaces/trace.py` 对 `append` 的后置条件）。
        self.sse(event)
        return event_id

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放某个 episode 的事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增且全部 > after_event_id。
        """
        assert after_event_id >= -1, f"after_event_id must be >= -1, got {after_event_id}"

        # 内部 list 本身就是按 event_id 升序追加的，不需要再排序。
        return [
            e
            for e in self._events
            if e.episode_id == episode_id and e.event_id > after_event_id
        ]

    def sse(self, event: TraceEvent) -> None:
        """推流：**现在直接打到控制台**，以后换成推给浏览器的 SSE 连接。

        只有 `append` 会调它。控制台格式和事件本身的字段是两回事——
        这里怎么排版、缩不缩进、要不要折行，都不影响 `TraceEvent`/`payload`
        长什么样，改这个方法不会动到事件流本身。
        """
        episode_id, step, type, source, p = (
            event.episode_id, event.step, event.type, event.source, event.payload
        )
        # episode 的开头/结尾不属于任何一步，不触发表头
        in_step = type not in (EventType.EPISODE_START, EventType.EPISODE_END)
        if in_step and self._step_shown != (episode_id, step):
            self._step_shown = (episode_id, step)
            print(f"\nstep {step}")

        if type is EventType.EPISODE_START:
            print(f"\n=== episode start  task={p.get('task_id','?')}  "
                  f"memory_carried={p.get('memory_carried','?')} ===")

        elif type is EventType.EPISODE_END:
            print(f"\n=== episode end  success={p.get('success','?')}  "
                  f"steps={p.get('steps','?')}  reason={p.get('reason','?')} ===")

        elif type is EventType.MODEL_CALL and source is Source.JUDGE:
            # 判定单独打一行，而且**把理由打出来**：成功率是要报的数字，
            # 每一个判定都得当场看得见它凭什么这么判。
            ok = "" if p.get("ok") == "True" else "  FAILED"
            # depth 要打出来：0 是任务目标，>0 是 agent 自己拆的子目标。
            # 不标的话满屏 judge 分不清哪次决定成败、哪次只是弹栈。
            at = f"  [depth {p['depth']}]" if "depth" in p else ""
            print(f"  {'judge_cost':<{LABEL_W}} {p.get('input_tokens','?')} in / "
                  f"{p.get('output_tokens','?')} out · {p.get('latency_ms','?')} ms{at}{ok}")
            self._wrapped("judge", p.get("raw", p.get("error", "")))

        elif type is EventType.MODEL_CALL:
            ok = "" if p.get("ok") == "True" else "  FAILED"
            label = COST_LABEL.get(source, f"{source.value}_cost")
            print(f"  {label:<{LABEL_W}} {p.get('input_tokens','?')} in / "
                  f"{p.get('output_tokens','?')} out · {p.get('latency_ms','?')} ms"
                  f"  (attempt {p.get('attempt','?')}){ok}")

        elif type is EventType.OBSERVE:
            print(f"  {'observe':<{LABEL_W}} {p.get('scene','?')}/{p.get('overlay','?')}"
                  f"   frame {p.get('frame_sha','?')}")
            # **目标栈跟着这一帧打出来**——不然"它是不是明知栈里已经有这条
            # 还是又压了一遍"这种问题只能翻回前面所有 goal +/goal ✓ 行手动重建。
            if p.get("goals"):
                print(f"  {'goals':<{LABEL_W}} {p['goals']}")
            for k, v in self._facts(p).items():
                if k in ("scene", "overlay"):
                    continue
                # walk_map 是多行的，缩进对齐后整块打出来，不能挤成一行
                head, *rest = str(v).splitlines() or [""]
                print(f"  {'':<{LABEL_W}} {k:<10} {head}")
                for line in rest:
                    print(f"  {'':<{LABEL_W}} {'':<10} {line}")

        elif type is EventType.MEMORY_READ:
            if p.get("count", "0") != "0":
                print(f"  {'recall':<{LABEL_W}} {p['count']} · {p.get('refs', '')}")

        elif type is EventType.THINK:
            self._wrapped("thought", p.get("thought", ""))
            # intent 不是 press 时 action 是空的，别打一个空字符串出来
            if p.get("action"):
                print(f"  {'action':<{LABEL_W}} {p['action']}{self._times(p)}")

        elif type is EventType.GOAL_PUSH:
            # 缩进随深度递增：目标栈是有层次的，**打成一列就看不出层次**，
            # 而"它拆到第几层了"正是判断目标栈有没有失控的那个数。
            pad = "  " * int(p.get("depth", "0"))
            print(f"  {'goal +':<{LABEL_W}} {pad}{p.get('goal','?')}")
            print(f"  {'':<{LABEL_W}} {pad}判据：{p.get('criteria','?')}")

        elif type is EventType.GOAL_POP:
            pad = "  " * int(p.get("depth", "0"))
            print(f"  {'goal ✓':<{LABEL_W}} {pad}{p.get('goal','?')}")
            self._wrapped("", p.get("why", ""))

        elif type is EventType.INSPECT:
            # 和 observe 分开显示：它是大脑主动问的，问了什么和答了什么都要看得见——
            # "它问的问题有没有价值"是判断这个动作值不值那次钱的唯一依据。
            self._wrapped("inspect ?", p.get("focus", ""))
            self._wrapped("inspect →", p.get("answer", ""))

        # ACT 事件不打印：动作本身已经由 THINK 那一行的 `action` 显示，
        # 而 `message` 就是执行后的新 summary，和下一步的 observe 完全重复。

        elif type is EventType.MEMORY_WRITE:
            # content 里带着 rationale —— 这一步为什么这么选，只有它记下来了。
            # **不再前置 `ref`**：`MemoryEntry.render()` 自己开头就是那个坐标，
            # 拼上去就成了 `(ep, 2) (ep, 2) 当时看到…`。
            self._wrapped("remember", p.get("content", ""))

        elif type is EventType.ERROR:
            self._wrapped("ERROR", p.get("reason", ""))

    @staticmethod
    def _facts(p: dict[str, str]) -> dict[str, str]:
        try:
            return json.loads(p.get("facts", "{}"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _wrapped(label: str, text: str) -> None:
        """整段打印，**不截断，且保留原有换行**。

        thought / remember / ERROR 是这一步的实质内容，截断等于把最该看的地方切掉。

        **先按原有换行拆，再对每一行做折行**：早一版直接 `textwrap.wrap(text)`，
        它会把所有换行当空白吃掉——于是 `remember` 里那张 10x9 的 walk_map
        被压成一条横着的字符串，正好是这一步最该看清的东西。
        """
        lines: list[str] = []
        for raw in text.splitlines() or [""]:
            lines.extend(textwrap.wrap(raw, width=88) or [""])
        print(f"  {label:<{LABEL_W}} {lines[0] if lines else ''}")
        for extra in lines[1:]:
            print(f"  {'':<{LABEL_W}} {extra}")

    @staticmethod
    def _times(p: dict[str, str]) -> str:
        """把 args 里的连按次数显示成 `×N`。

        **「模型明确给了 1」和「模型压根没给 times」必须区分开**——
        这两者长得一样的话，你分不清是「它选择不连按」还是「它不知道能连按」，
        而这两个问题的修法完全不同（前者调 prompt 措辞，后者查渲染链路）。
        """
        try:
            args = json.loads(p.get("args", "{}"))
        except json.JSONDecodeError:
            return "   [args 不是合法 JSON]"
        if "times" not in args:
            return "   [无 times]"
        try:
            n = int(args["times"])
        except (ValueError, TypeError):
            return f"   [times={args['times']!r} 非法]"
        return f" ×{n}" if n > 1 else " ×1"

    # ---- 便于测试与调试，不属于 TracePort 契约 ----

    def all_events(self) -> list[TraceEvent]:
        """全部事件（含所有 episode）。测试断言用。"""
        return list(self._events)

    def count(self, episode_id: str, type: EventType) -> int:
        """某个 episode 里某类事件的条数。测试断言重试次数、失败次数用。"""
        return sum(1 for e in self._events if e.episode_id == episode_id and e.type is type)
