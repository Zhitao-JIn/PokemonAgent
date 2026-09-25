"""`Tape`：一段录下的账（磁带），与回放时"读到哪了"的游标。

回放的五个磁带件（`TapeTrace` / `TapeGame` / `TapeMemory` / `TapeReviewer` / `TapeProvider`）
共用一卷磁带：

- **可比的账**逐条对上——harness 每记一笔，`TapeTrace` 就拿它与磁带上下一条可比的账比
  （`kind`、正文、`meta` 除 `run_id` / `branch`），对不上抛 `ReplayDiverged`；
- 取东西的磁带件（感知、动作空间、记忆读、问人）**先看后记**：它被调用时，对应的那笔账还没记，
  所以从游标往后找第一条同种的账取值（`peek`），随后 harness 记账时由 `TapeTrace` 核对并推进；
- 模型调用另排一队（`next_call`）：按发生顺序逐次取出，先核 prompt 与录下的逐字相同。

不可比的账：模型调用账与它连带的 `call_failed`（尝试次数由模型调用队列本身核对）、
存档一族（回放段里存档器暂停）。
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pokemon_agent.schemas.harness import ModelCall
from pokemon_agent.schemas.harness.domain import TraceEvent

from .errors import ReplayDiverged

MODEL_CALL_TYPE = "model_call"
NOT_COMPARED_KINDS = frozenset(
    {
        "call_failed",
        "summary_parse_error",
        "checkpoint_save",
        "checkpoint_restore",
        "world_snapshot",
        "trace_sealed",
        "checkpoint_error",
    }
)
"""不逐条比对的账名（模型调用账按 type 另外排除）。"""

RENDER_EXTRAS = {"judge_call": ("why",), "verify_call": ("verdicts",)}
"""渲染层在这两本调用账上额外挂的字段（不属于调用本身的 payload，还原时去掉）。"""

PERCEPTION_CALL_KIND = "sense_call"
"""感知的模型调用：回放时整条感知由 `TapeGame` 顶替，这一族不进模型调用队列。"""

ERROR_TYPE = "error"


def comparable(event: TraceEvent) -> bool:
    """这条账要不要逐条比对。"""
    return event.type != MODEL_CALL_TYPE and event.kind not in NOT_COMPARED_KINDS


def event_meta(event: TraceEvent) -> dict[str, Any]:
    """事件的签名信息，去掉落盘层盖的 `run_id` / `branch`。"""
    meta = json.loads(event.meta)
    meta.pop("run_id", None)
    meta.pop("branch", None)
    return meta


def event_content(event: TraceEvent) -> Any:  # noqa: ANN401 —— 正文本来就是任意 JSON
    return json.loads(event.content)


@dataclass(frozen=True)
class RecordedCall:
    """一次录下的模型调用：`payload` 原样，失败时带异常类名与原文。"""

    kind: str
    payload: dict[str, Any]
    error_kind: str = ""
    error: str = ""

    def as_model_call(self) -> ModelCall:
        return ModelCall(payload=self.payload, error_kind=self.error_kind, error=self.error)


@dataclass
class Tape:
    """一卷磁带：录下的一段账、目标（第几局的哪个 task）、以及切换时要做的事。

    events：起点存档之后、目标 task 的 `task_start` 之前，按 `(ts, uuid)` 排好的全部账。
    target_episode / target_task：回放到哪个 task 开局为止。
    """

    events: Sequence[TraceEvent]
    target_episode: str
    target_task: str
    on_switch: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    """切换时依次调用，参数是目标 `task_start` 的 `meta`。"""
    switched: bool = False
    diverged: ReplayDiverged | None = None
    """第一次走偏的原因；此后磁带上的任何操作都原样再抛它（别让收场代码的账盖住真正的原因）。"""
    _cursor: int = 0
    _calls: deque[RecordedCall] = field(init=False)

    def __post_init__(self) -> None:
        self._calls = deque(_recorded_calls(self.events))

    # ---- 可比的账 ----

    def peek(self, kinds: frozenset[str] | set[str]) -> TraceEvent:
        """从游标往后第一条 `kind` 属于 `kinds` 的可比账（不推进）。找不到 → `ReplayDiverged`。"""
        self._raise_if_diverged()
        for event in self.events[self._cursor :]:
            if comparable(event) and event.kind in kinds:
                return event
        raise self._diverge(f"磁带上游标之后没有 {sorted(kinds)} 这种账")

    def check(self, kind: str, meta: dict[str, Any], content: Any) -> None:  # noqa: ANN401
        """把 harness 刚记的一笔与磁带上下一条可比账比对，对上就推进游标。"""
        self._raise_if_diverged()
        event = self._next_comparable()
        if event is None:
            raise self._diverge(f"磁带已放完，却又记了一笔 {kind}")
        expected = (event.kind, event_meta(event), event_content(event))
        actual = (kind, json.loads(json.dumps(meta, ensure_ascii=False)), _jsonable(content))
        if expected != actual:
            raise self._diverge(f"回放分叉：应为 {expected}，实为 {actual}")
        self._cursor += 1

    def remaining(self) -> list[TraceEvent]:
        """游标之后还没对上的可比账。"""
        return [e for e in self.events[self._cursor :] if comparable(e)]

    def played(self) -> list[TraceEvent]:
        """游标之前的全部账（回放到此刻"本该已经写出"的那些）。"""
        return list(self.events[: self._cursor])

    def _next_comparable(self) -> TraceEvent | None:
        while self._cursor < len(self.events) and not comparable(self.events[self._cursor]):
            self._cursor += 1
        return self.events[self._cursor] if self._cursor < len(self.events) else None

    # ---- 模型调用 ----

    def next_call(self, prompt: str) -> RecordedCall:
        """取下一次录下的模型调用，先核 prompt 逐字相同。"""
        self._raise_if_diverged()
        if not self._calls:
            raise self._diverge("磁带上的模型调用已经用完，却又问了一次模型")
        call = self._calls.popleft()
        if call.payload.get("prompt") != prompt:
            raise self._diverge(f"回放分叉：这次 {call.kind} 的 prompt 与录下的不同")
        return call

    def perception_calls_before(self, event: TraceEvent) -> list[ModelCall]:
        """`event` 之前、游标之后录下的感知调用（感知耗尽时要随异常带出去）。"""
        stop = next(i for i, e in enumerate(self.events) if e is event)
        window = self.events[self._cursor : stop]
        return [c.as_model_call() for c in _recorded_calls(window, perception=True)]

    # ---- 切换 ----

    def switch(self, task_meta: dict[str, Any]) -> None:
        """走到目标 task 开局：磁带必须恰好放完，然后依次做切换要做的事。"""
        self._raise_if_diverged()
        left = self.remaining()
        if left:
            raise self._diverge(f"走到目标 task 时磁带还剩 {len(left)} 笔没对上：{left[0].kind}…")
        if self._calls:
            raise self._diverge(f"走到目标 task 时还有 {len(self._calls)} 次模型调用没用上")
        self.switched = True
        for hook in self.on_switch:
            hook(task_meta)

    def diverge(self, message: str) -> ReplayDiverged:
        """记下走偏的原因并返回它（调用方 `raise`）；磁带件发现对不上时用。"""
        return self._diverge(message)

    def _diverge(self, message: str) -> ReplayDiverged:
        self.diverged = ReplayDiverged(message)
        return self.diverged

    def _raise_if_diverged(self) -> None:
        if self.diverged is not None:
            raise self.diverged


def _recorded_calls(
    events: Sequence[TraceEvent], *, perception: bool = False
) -> list[RecordedCall]:
    """从账里还原模型调用：每条调用账紧跟着的错误账（若有）就是它的失败原因。

    perception：只要感知调用（True）或只要感知以外的（False）。
    """
    out: list[RecordedCall] = []
    for i, event in enumerate(events):
        if event.type != MODEL_CALL_TYPE or (event.kind == PERCEPTION_CALL_KIND) != perception:
            continue
        follow = events[i + 1] if i + 1 < len(events) else None
        error_kind = error = ""
        if follow is not None and follow.type == ERROR_TYPE and follow.kind != "call_exhausted":
            body = event_content(follow)
            error_kind = body.get("exception", "ParseFailure")
            error = body.get("reason", "")
        payload = event_content(event)
        for extra in RENDER_EXTRAS.get(event.kind, ()):
            payload.pop(extra, None)
        out.append(RecordedCall(event.kind, payload, error_kind, error))
    return out


def _jsonable(content: Any) -> Any:  # noqa: ANN401
    return json.loads(json.dumps(content, ensure_ascii=False))


__all__ = [
    "NOT_COMPARED_KINDS",
    "RecordedCall",
    "Tape",
    "comparable",
    "event_content",
    "event_meta",
]
