"""校验判定的最小值对象：`VerifyVerdict`。

它是校验那一次调用（`Brain.verify()`）的响应元素：
`FromHarnessToBrainToolVerifyResp.verdicts` 用它表示"对一条 entries 的判定"。
`verify` 现在服务**两级标记**（0923 192）：task 层 `task_done` 标 ActMemory、
episode 层 `verify_task_memories` 标 TaskMemory——所以它不再叫
`StepVerifyVerdict`（"step"只是它最早服务的那一级）。

**语义是正/负样本，不是可信度（0923 192 定）**：verify 只回答"这条行为/总结
符不符合 goal"——符合是正样本（`positive=True`），不符合是负样本。act 直接从
机器读出、是最忠实的证据，没有"信不信"问题；verify 是**标记器**：标注连同原记录
**正负都送**给下游蒸馏作参考（196 起不再只留正样本），不是审判官。

**它只服务校验，与蒸馏无关。** `verify`/`summarize` 原本合并成
`Brain.verify_and_summarize()` 的一次调用，那一族的 `VerifyAndSummarizeReq/Resp`
信封随拆分一起删除（CHANGELOG 第 39 条），现在是两次独立调用、两套信封：
`FromHarnessToBrainToolVerify{,Resp}` 与 `...Summarize{,Resp}`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VerifyVerdict(BaseModel):
    """对一条 entries（ActMemory 或 TaskMemory）的判定。"""

    index: int = Field(ge=0, description="对应 entries 的下标")
    positive: bool = Field(description="这条行为/总结是否符合 goal：符合=正样本")
    why: str = Field(description="依据——判负样本时要说清不符合在哪")


__all__ = ["VerifyVerdict"]
