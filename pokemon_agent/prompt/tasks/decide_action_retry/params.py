"""重试只接受基础请求、次数与本次错误原件。"""

from pydantic import BaseModel


class DecideActionRetryParams(BaseModel):
    base_prompt: str
    attempt: int
    reason: str
    raw: str
