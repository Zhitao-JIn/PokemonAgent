"""verify 的独立原料契约。"""

from pydantic import BaseModel

from ...records import ActRecord, TaskRecord


class VerifyParams(BaseModel):
    goal: str
    knowledge: str = ""
    entries: list[ActRecord | TaskRecord]
