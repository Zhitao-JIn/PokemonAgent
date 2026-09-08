"""校验判定的最小值对象：`StepVerifyVerdict`。

verify_steps 与 summarize 的调用链已合并为
`FromBrainToolToBrainVerifyAndSummarizeReq`/`FromBrainToolToBrainVerifyAndSummarizeResp`
（`schemas/communication/verify_and_summarize.py`）——见
`docs/ROADMAP.md`“verify_steps 与 summarize 合并”一条。`StepVerifyVerdict`
仍被两处复用：合并后的响应用它表示“对一条 step 记忆的
判定”（`FromBrainToolToBrainVerifyAndSummarizeResp.verdicts`），`trace/utils.py::verify_call()`
落 trace 时也按这个形状序列化。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StepVerifyVerdict(BaseModel):
    """对一条 step 记忆的判定。"""

    index: int = Field(ge=0, description="对应 entries 的下标")
    reliable: bool = Field(description="这条记录是否可信（动作与变化一致、无矛盾）")
    why: str = Field(description="依据——不可靠时要说清矛盾在哪")
