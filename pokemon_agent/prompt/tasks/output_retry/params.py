"""输出纠正附录：基础请求、次数、本次错误原件，以及是否附动作空间说明。"""

from pydantic import BaseModel, Field


class OutputRetryParams(BaseModel):
    base_prompt: str
    attempt: int
    reason: str
    raw: str
    include_action_space_note: bool = Field(
        default=False,
        description="只有 decide_action 会收到'不在 action space 里'这一段的说明",
    )
