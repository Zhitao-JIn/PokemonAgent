"""summarize_task 的独立原料契约。"""

from pydantic import BaseModel

from ...records import ActRecord, VerdictRecord


class SummarizeTaskParams(BaseModel):
    goal: str
    task_id: str
    entries: list[ActRecord]
    verdicts: list[VerdictRecord]
    termination: str
    success: bool
    judge_reason: str = ""
    steps_used: int
    max_steps: int
