"""把事件流实时打到控制台的 TracePort 装饰器。

挂点选在 trace 而不是往图节点里塞 print，有两个理由：

- **trace 本来就是事件流**，实时观测和事后 replay 看的是同一份数据。
  往节点里加 print 会产生第二份「只有控制台有」的信息，两边迟早对不上。
- 它演示了那条分层：换 trace 实现 = 换观测方式，上面所有代码一行不动。
  真正的 SSE 观测台（阶段 2）也是同一个挂点，只是把 print 换成推流。

装饰而不是替代：真实现照常收到全部事件，打印只是旁路。
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Iterable

from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.schemas.core import EventType, Source, TraceEvent

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


class EchoTrace:
    """包住任意 TracePort，顺手打印。"""

    def __init__(self, inner: TracePort) -> None:
        self._inner = inner
        self._step_shown: tuple[str, int] | None = None
        """这一步的表头打过没有。

        表头是 **step 的标题**，不是某个事件的标题，所以由步号变化触发。
        挂在 OBSERVE 上是不行的：事件流里 `model_call(perception)` 在它前面
        （那是因果顺序，产出观测的调用当然更早），表头就会打在本步的成本行下面，
        看日志的人把那行成本读成上一步的。

        排版问题在这里解决，**不去改事件流**——trace 是唯一的事实来源。
        """

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
    ) -> int:
        event_id = self._inner.append(episode_id, step, type, source, payload)
        self._echo(episode_id, event_id, step, type, source, payload or {})
        return event_id

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        return self._inner.replay(episode_id, after_event_id)

    def __getattr__(self, name: str) -> object:
        """其余方法（all_events / count 等）透传给被包住的实现。"""
        return getattr(self._inner, name)

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

    def _echo(
        self, episode_id: str, event_id: int, step: int, type: EventType,
        source: Source, p: dict[str, str],
    ) -> None:
        # episode 的开头/结尾不属于任何一步，不触发表头
        in_step = type not in (EventType.EPISODE_START, EventType.EPISODE_END)
        if in_step and self._step_shown != (episode_id, step):
            self._step_shown = (episode_id, step)
            print(f"\nstep {step}")

        # episode 的开头/结尾不属于任何一步，不触发表头
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
