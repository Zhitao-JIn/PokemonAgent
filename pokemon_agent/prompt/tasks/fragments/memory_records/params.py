"""记忆片段只接收独立记录与标注。"""

from typing import Literal

from pydantic import BaseModel, Field

from ....observation import ObservationRecord
from ....records import ActRecord, EpisodeRecord, RunRecord, TaskRecord, VerdictRecord


class MemoryParams(BaseModel):
    mode: Literal[
        "verify",
        "verify_entries",
        "summarize",
        "summarize_task",
        "summarize_run",
        "sequence",
        "plain",
        "index",
        "observation",
    ]
    entries: list[ActRecord | TaskRecord | EpisodeRecord | RunRecord]
    verdicts: list[VerdictRecord] = Field(default_factory=list)

    serialized: bool = False

    observation: ObservationRecord | None = None
