"""summarize 的独立原料契约。"""

from pydantic import BaseModel

from ...records import TaskRecord, VerdictRecord


class SummarizeParams(BaseModel):
    goal: str
    entries: list[TaskRecord]
    verdicts: list[VerdictRecord]
    termination: str
    success: bool
    judge_reason: str = ""
    steps: int
    max_steps: int
