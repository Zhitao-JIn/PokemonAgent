"""校验判定的最小值对象：`StepVerifyVerdict`。

它是校验那一次调用（`Brain.verify()`）的响应元素：
`FromHarnessToBrainToolVerifyResp.verdicts` 用它表示"对一条 step 记忆的判定"。

**它只服务校验，与蒸馏无关。** `verify`/`summarize` 原本合并成
`Brain.verify_and_summarize()` 的一次调用，那一族的 `VerifyAndSummarizeReq/Resp`
信封随拆分一起删除（CHANGELOG 第 39 条），现在是两次独立调用、两套信封：
`FromHarnessToBrainToolVerify{,Resp}` 与 `...Summarize{,Resp}`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StepVerifyVerdict(BaseModel):
    """对一条 step 记忆的判定。"""

    index: int = Field(ge=0, description="对应 entries 的下标")
    reliable: bool = Field(description="这条记录是否可信（动作与变化一致、无矛盾）")
    why: str = Field(description="依据——不可靠时要说清矛盾在哪")
