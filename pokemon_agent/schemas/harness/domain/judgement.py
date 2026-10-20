"""判定员的单一语义结论；布尔读法只从 decision 派生。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Judgement(BaseModel):
    """一次裁决；任务之外能否使用 interrupted 由调用方验证。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["achieved", "continue", "blocked", "interrupted"]
    why: str = Field(min_length=1)

    @property
    def done(self) -> bool:
        """本层目标是否达成。"""
        return self.decision == "achieved"

    @property
    def interrupted(self) -> bool:
        """task 是否被意外打断。"""
        return self.decision == "interrupted"

    @property
    def blocked(self) -> bool:
        """本层是否无法推进。"""
        return self.decision == "blocked"
