# pokemon_agent/trace/store.py

import os
import json
import textwrap
from pathlib import Path
from typing import Dict, Any, Iterable
from datetime import datetime

from pokemon_agent.schemas.trace import TraceEvent, EventType, Source, TRACE_SCHEMA_VERSION
from .index import EpisodeIndex

# 项目根目录（通过 __file__ 回溯三级）
project_root = Path(__file__).parent.parent.parent
# 数据存储目录（在项目根目录下）
STORAGE_ROOT = project_root / "trace_data"

LABEL_W = 15
"""标签列宽，由最长的标签 `perception_cost` 决定。写成常量而不是散在各处的
`:<9`，是因为对齐一旦不一致，多行的 `thought` 会和单行的 `action` 错开——
读日志的人第一眼看到的就是排版乱，而不是内容。
"""

COST_LABEL: dict[Source, str] = {
    Source.PERCEPTION: "perception_cost",
    Source.DECISION: "decision_cost",
    Source.JUDGE: "judge_cost",
}

PHASE_BY_TYPE: dict[EventType, str] = {
    EventType.OBSERVE: "observe", EventType.MODEL_CALL: "model_call",
    EventType.THINK: "think", EventType.ACT: "act",
    EventType.MEMORY_READ: "retrieve_memory", EventType.MEMORY_WRITE: "memory_write",
    EventType.OBJECT_NOTE: "memory_write", EventType.EPISODE_MEMORY_WRITE: "memory_write",
    EventType.INSPECT: "inspect", EventType.GOAL_PUSH: "goal", EventType.GOAL_POP: "goal",
    EventType.ERROR: "error", EventType.EPISODE_START: "episode",
    EventType.EPISODE_END: "episode", EventType.CHECKPOINT: "checkpoint",
}
"""MODEL_CALL 事件的标签，要带 `_cost` 后缀：这一行报的是这次调用花了多少
（token、延迟），不是"感知到了什么"，混进 `perception`/`observe` 会当成一件事。
"""


class LocalTrace:
    def __init__(self, run_id: str = "local", sse_sink: object | None = None) -> None:
        self._run_id = run_id
        self._sse_sink = sse_sink
        self._run_dir = STORAGE_ROOT / run_id
        self._episodes_dir = self._run_dir / "episodes"
        self._events: list[TraceEvent] = []
        self._next_id = 0
        self._step_shown: tuple[str, int] | None = None
        """这一步的表头打过没有，`sse()` 用。表头由 step 值变化触发，不挂在
        `OBSERVE` 上——`MODEL_CALL(perception)` 因果顺序上先于 `OBSERVE`，
        挂在 `OBSERVE` 上表头会打在本步成本行下面。
        """

        # 确保存储结构
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._episodes_dir.mkdir(exist_ok=True)

        # 清理之前未完成的episodes
        EpisodeIndex.clean_incomplete_episodes(run_id)

    def append(self, episode_id: str, step: int, type: EventType,
               source: Source, payload: dict[str, str] | None = None) -> int:
        # 校验前置条件
        assert step >= 0, "step 必须非负"

        # 生成 event_id
        event_id = self._next_id
        self._next_id += 1

        # 构造完整事件
        event = TraceEvent(
            event_id=event_id,
            run_id=self._run_id,
            episode_id=episode_id,
            step=step,
            type=type,
            phase=PHASE_BY_TYPE.get(type, type.value),
            source=source,
            payload=payload or {},
            ts=(datetime.combine(datetime.min, datetime.now().time()) - datetime.min).total_seconds(),
            schema_version=TRACE_SCHEMA_VERSION,
        )

        # 验证全局唯一性
        if event_id == 0 and not EpisodeIndex.is_unique(episode_id, self._run_id):
            raise ValueError(f"严重错误: episode_id '{episode_id}' 已存在! 原因: 不允许覆盖已完成的阶段")

        # 持久化到磁盘
        self._save_event(event)

        # 内存存储
        self._events.append(event)
        assert event_id == self._events[-1].event_id  # 确保单调性

        # 推流到 SSE
        self.sse(event)

        return event_id

    def _save_event(self, event: TraceEvent) -> None:
        """原子化写入事件到 JSONL 文件"""
        episode_path = self._episodes_dir / f"{event.episode_id}.jsonl"
        temp_path = episode_path.with_suffix(".jsonl.tmp")

        # 1. 写入临时文件
        with temp_path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

        # 2. 原子化重命名
        try:
            os.replace(temp_path, episode_path)
        except AttributeError:  # Windows 不支持 os.replace
            if episode_path.exists():
                os.remove(episode_path)
            os.rename(temp_path, episode_path)

        # 3. 更新索引
        EpisodeIndex.register(event.episode_id, event.run_id)

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """从磁盘加载事件流"""
        # 1. 检查内存缓存
        cached = [e for e in self._events
                  if e.episode_id == episode_id and e.event_id > after_event_id]
        if cached:
            return sorted(cached, key=lambda e: e.event_id)

        # 2. 从磁盘加载
        episode_path = self._episodes_dir / f"{episode_id}.jsonl"
        if not episode_path.exists():
            return []

        events = []
        with episode_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    event = TraceEvent.model_validate_json(line.strip())
                    if event.event_id > after_event_id:
                        events.append(event)
                except json.JSONDecodeError:
                    pass

        # 3. 严格排序
        return sorted(events, key=lambda e: e.event_id)

    def sse(self, event: TraceEvent) -> None:
        """把这条事件推给当前的观测通道——现在打印到控制台，以后是浏览器推流。

        调用点不变，换的只是这一个方法内部的实现。
        """
        if callable(self._sse_sink):
            self._sse_sink(event)
        ep, step, type_, source = event.episode_id, event.step, event.type, event.source
        p = event.payload

        if type_ in (EventType.OBSERVE, EventType.MEMORY_READ, EventType.THINK,
                     EventType.ACT, EventType.INSPECT, EventType.MEMORY_WRITE):
            return

        # 表头逻辑（在所有分支之前）：EPISODE_START/END 不属于某一步，跳过。
        if type_ not in (EventType.EPISODE_START, EventType.EPISODE_END):
            if self._step_shown != (ep, step):
                print(f"\n----- STEP {step} -----")
                self._step_shown = (ep, step)

        if type_ is EventType.EPISODE_START:
            print(f"\n{'=' * 62}")
            print(f"episode {ep} start  task={p.get('task_id', '')}  "
                  f"goal={p.get('goal', '')}  max_steps={p.get('max_steps', '')}  "
                  f"memory_carried={p.get('memory_carried', '')}")

        elif type_ is EventType.EPISODE_END:
            print(f"\nepisode {ep} end  success={p.get('success', '')}  "
                  f"steps={p.get('steps', '')}  reason={p.get('reason', '')}")
            print(self._wrapped("why", p.get("why", "")))
            print("=" * 62)

        elif type_ is EventType.MODEL_CALL:
            label = COST_LABEL.get(source, f"{source.value}_cost")
            depth = f" depth={p['depth']}" if "depth" in p else ""
            print(f"{label:<{LABEL_W}} in={p.get('input_tokens', '?')} "
                  f"out={p.get('output_tokens', '?')} "
                  f"latency={p.get('latency_ms', '?')}ms "
                  f"attempt={p.get('attempt', '?')} ok={p.get('ok', '?')}{depth}")

        elif type_ is EventType.OBSERVE:
            print(f"{'observe':<{LABEL_W}} scene={p.get('scene', '')} "
                  f"overlay={p.get('overlay', '')} frame={p.get('frame_sha', '')[:8]}")
            print(self._wrapped("summary", p.get("summary", "")))
            facts = self._facts(p)
            if facts.get("walk_map"):
                print(self._wrapped("walk_map", facts["walk_map"]))
            if p.get("goals"):
                print(self._wrapped("goals", p["goals"]))

        elif type_ is EventType.MEMORY_READ:
            print("--- MEMORY RETRIEVAL ---")
            print(f"{'step_memory':<{LABEL_W}} count={p.get('step_memory_count', p.get('count', '0'))} "
                  f"refs={p.get('refs', '')}")
            print(f"{'known_object':<{LABEL_W}} {p.get('known_object_names', '(无)')}")
            print(f"{'knowledge':<{LABEL_W}} {p.get('knowledge_titles', '(无)')}")
            print(f"{'episode_level':<{LABEL_W}} "
                  f"count={p.get('episode_level_count', p.get('episode_memory_count', '0'))} "
                  f"refs={p.get('episode_memory_refs', '')}")

        elif type_ is EventType.THINK:
            # 上一版这里连 action/×N/第几次尝试 一起打印，跟紧随其后的 ACT
            # 那一行（本来就有 action/×N）重复，是那部分该去掉——不是把
            # thought 本身也一起去掉。推理文字还是要看的，只是不用再重复
            # 报一遍这次选了哪个动作。
            print(self._wrapped("thought", p.get("thought", "")))

        elif type_ is EventType.ACT:
            times = self._times(p)
            print(f"{'act':<{LABEL_W}} action={p.get('action', '')}{times}  "
                  f"{p.get('message', '')}")

        elif type_ is EventType.MEMORY_WRITE:
            # payload["key"] 目前是 MemoryEntry.key——本阶段只是"位置占位"
            # （见 schemas/memory_episodic.py 的字段说明，检索现在也不靠它，
            # 靠 Snapshot 字符重叠），打出来除了一串坐标什么都看不出，不如不印。
            print(f"{'remember':<{LABEL_W}} 写入一条情景记忆")

        elif type_ is EventType.OBJECT_NOTE:
            print(f"{'object_note':<{LABEL_W}} key={p.get('key', '')} kind={p.get('kind', '')}")
            print(self._wrapped("content", p.get("content", "")))

        elif type_ is EventType.GOAL_PUSH:
            print(f"{'goal_push':<{LABEL_W}} depth={p.get('depth', '')} "
                  f"goal={p.get('goal', '')}")
            print(self._wrapped("criteria", p.get("criteria", "")))

        elif type_ is EventType.GOAL_POP:
            print(f"{'goal_pop':<{LABEL_W}} depth={p.get('depth', '')} "
                  f"reason={p.get('reason', '')} goal={p.get('goal', '')}")
            if p.get("why"):
                print(self._wrapped("why", p["why"]))

        elif type_ is EventType.INSPECT:
            print(f"{'inspect':<{LABEL_W}} focus={p.get('focus', '')}")
            print(self._wrapped("answer", p.get("answer", "")))

        elif type_ is EventType.ERROR:
            print(f"{'ERROR':<{LABEL_W}} kind={p.get('kind', '')} "
                  f"attempt={p.get('attempt', '')}")
            print(self._wrapped("reason", p.get("reason", "")))

        else:
            print(f"{type_.value:<{LABEL_W}} {p}")

    @staticmethod
    def _wrapped(label: str, text: str) -> str:
        """整段打印，不截断、保留原有换行——先按原有换行拆分，再对每一行分别
        折行（宽度 88），不对整段文本直接 `textwrap.wrap`（那样会把原有换行
        当普通空白吃掉，压坏多行内容，例如 `walk_map`）。
        """
        if not text:
            return f"{label:<{LABEL_W}}"
        lines = []
        for i, raw_line in enumerate(str(text).split("\n")):
            wrapped = textwrap.wrap(raw_line, width=88) or [""]
            for j, line in enumerate(wrapped):
                prefix = f"{label:<{LABEL_W}}" if i == 0 and j == 0 else " " * LABEL_W
                lines.append(f"{prefix}{line}")
        return "\n".join(lines)

    @staticmethod
    def _facts(p: dict[str, str]) -> dict[str, Any]:
        """把 payload["facts"]（JSON 字符串）解析成 dict，解析失败时返回空 dict。"""
        try:
            return json.loads(p.get("facts", "{}"))
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _times(p: dict[str, str]) -> str:
        """把 args JSON 里的 times（连按次数）格式化成 `×N`。必须区分"模型
        明确给了 1"和"模型压根没给 times"——修法完全不同（前者调 prompt 措辞，
        后者排查渲染链路是否把这个能力告诉了模型）。
        """
        try:
            args = json.loads(p.get("args", "{}"))
        except (json.JSONDecodeError, TypeError):
            return " [args 不是合法 JSON]"
        if "times" not in args:
            return " [无 times]"
        try:
            n = int(args["times"])
        except (TypeError, ValueError):
            return f" [times={args['times']} 非法]"
        return f" ×{n}"

    def all_events(self) -> list[TraceEvent]:
        """获取所有事件（供测试使用）"""
        return self._events


# 兼容旧测试和外部脚本；新代码统一使用 LocalTrace。
MockTrace = LocalTrace
