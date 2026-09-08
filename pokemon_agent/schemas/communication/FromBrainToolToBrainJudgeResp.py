"""`BrainTool` → `Brain` 这一跳的判定响应协议：
`FromBrainToolToBrainJudgeResp`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.domain import ModelCall


class FromBrainToolToBrainJudgeResp(BaseModel):
    """**大脑给出的判定**结果，连同它花了什么。

    跨层了才做成模型：大脑产出它，Harness 读 `done` 决定要不要终止、
    把 `call` 写进 trace。两边对这三个字段的期待必须是同一份契约。
    """

    done: bool = Field(description="任务达成了没有。**拿不准一律 False**")
    why: str = Field(
        description="看到了什么证据（或为什么证据不足）。"
        "每一个 True 都得说得出依据，否则成功率就是一个无法证伪的数字"
    )
    call: ModelCall = Field(
        default_factory=lambda: ModelCall(),
        description="这次判定的账。判定和决策各自烧 token，分不开就说不清"
        "「成功率这个数字本身花了多少钱」，也算不出判定器自己的失效率——"
        "而**没有失效率的判定器等于没有判定器**",
    )
