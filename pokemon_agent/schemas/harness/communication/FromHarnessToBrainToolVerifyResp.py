"""`FromHarnessToBrainToolVerifyResp`：`BrainTool` → harness 的校验响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import StepVerifyVerdict

from .ModelCall import ModelCall


class FromHarnessToBrainToolVerifyResp(BaseModel):
    """`BrainTool.verify()` 交回给 harness 的校验结果。

    **拿不到结果时抛 `MaxRetriesExceeded`**（整条账在异常里）——旧契约的
    "解析失败就把全部条目标不可靠"已废弃：那与"这一局的记忆确实都不可信"
    在结果上无法区分。需要那份保守结果时由 harness 在 `except` 里自行构造。

    verdicts：与 `req.entries` 等长、按 `index` 顺序——`index` 落回
        `entries` 的下标，调用方据此知道"是哪一条不可信"。
    """

    verdicts: list[StepVerifyVerdict] = Field(description="与 entries 等长的判定列表")
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )
