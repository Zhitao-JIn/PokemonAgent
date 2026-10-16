"""读侧出口：一条落盘事件 → 类型化事件（封套 + `EventMeta` + 按 `kind` 分派的正文模型）。

与 `render.py` 成对：那边把领域对象写成正文，这边把正文读回类型。测评等读账的一方只从这里取，
不自己 `json.loads` 再按字符串键摸字段。没建模的账读成 `OtherContent`（原样保留全部键）。

sense_call 已停止产出；相关类型与映射仅为读取旧账保留。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from pokemon_agent.schemas.harness import TraceEvent, TraceKind

from .content import (
    ActCallContent,
    CallExhaustedContent,
    CallFailedContent,
    CheckpointRestoreContent,
    CheckpointSaveContent,
    CheckStallContent,
    ChooseVerdictContent,
    DecomposeVerdictContent,
    EpisodeEndContent,
    EpisodeStartContent,
    ErrorEndContent,
    EventMeta,
    JudgeVerdictContent,
    ModelCallContent,
    OtherContent,
    PlanVerdictContent,
    RunEndContent,
    RunStartContent,
    SenseFrameContent,
    SettleGoalContent,
    SummaryParseErrorContent,
    TaskEndContent,
    TaskStartContent,
    VerifyVerdictContent,
)

CONTENT_MODELS: dict[str, type[BaseModel]] = {
    TraceKind.RUN_START: RunStartContent,
    TraceKind.RUN_END: RunEndContent,
    TraceKind.RUN_ERROR: ErrorEndContent,
    TraceKind.EPISODE_START: EpisodeStartContent,
    TraceKind.EPISODE_END: EpisodeEndContent,
    TraceKind.EPISODE_ERROR: ErrorEndContent,
    TraceKind.TASK_START: TaskStartContent,
    TraceKind.TASK_END: TaskEndContent,
    TraceKind.TASK_ERROR: ErrorEndContent,
    TraceKind.SENSE_FRAME: SenseFrameContent,
    TraceKind.CHOOSE_VERDICT: ChooseVerdictContent,
    TraceKind.ACT_CALL: ActCallContent,
    TraceKind.CHECK_STALL: CheckStallContent,
    TraceKind.JUDGE_VERDICT: JudgeVerdictContent,
    TraceKind.DECOMPOSE_VERDICT: DecomposeVerdictContent,
    TraceKind.PLAN_VERDICT: PlanVerdictContent,
    TraceKind.VERIFY_VERDICT: VerifyVerdictContent,
    TraceKind.SENSE_CALL: ModelCallContent,
    TraceKind.CHOOSE_CALL: ModelCallContent,
    TraceKind.PLAN_CALL: ModelCallContent,
    TraceKind.DECOMPOSE_CALL: ModelCallContent,
    TraceKind.JUDGE_CALL: ModelCallContent,
    TraceKind.VERIFY_CALL: ModelCallContent,
    TraceKind.SUMMARIZE_EPISODE_CALL: ModelCallContent,
    TraceKind.SUMMARIZE_TASK_CALL: ModelCallContent,
    TraceKind.CALL_FAILED: CallFailedContent,
    TraceKind.CALL_EXHAUSTED: CallExhaustedContent,
    TraceKind.SUMMARY_PARSE_ERROR: SummaryParseErrorContent,
    TraceKind.CHECKPOINT_SAVE: CheckpointSaveContent,
    TraceKind.CHECKPOINT_RESTORE: CheckpointRestoreContent,
    TraceKind.SETTLE_GOAL: SettleGoalContent,
}
"""账名 → 正文模型。键是 `TraceKind`（`StrEnum`，与落盘的 `kind` 字符串逐字相等）。"""

MODEL_CALL_KINDS: frozenset[str] = frozenset(
    kind for kind, model in CONTENT_MODELS.items() if model is ModelCallContent
)
"""九条链路的调用账（`*_call`）。"""


class ParsedEvent(BaseModel):
    """一条类型化的事件。`content` 的具体类型由 `kind` 决定（见 `CONTENT_MODELS`）。"""

    uuid: str
    kind: str
    type: str
    started_at: float
    ended_at: float
    meta: EventMeta
    content: BaseModel


def parse(event: TraceEvent) -> ParsedEvent:
    """把一条落盘事件读成类型化事件。

    失败：`meta` / `content` 不是合法 JSON，或正文与该账的模型对不上 → pydantic `ValidationError`
    （`ValueError` 子类）。没建模的账不报错，读成 `OtherContent`。
    """
    model = CONTENT_MODELS.get(event.kind, OtherContent)
    return ParsedEvent(
        uuid=event.uuid,
        kind=event.kind,
        type=event.type,
        started_at=event.started_at,
        ended_at=event.ended_at,
        meta=EventMeta.model_validate(json.loads(event.meta)),
        content=model.model_validate(json.loads(event.content)),
    )


__all__ = ["CONTENT_MODELS", "MODEL_CALL_KINDS", "ParsedEvent", "parse"]
