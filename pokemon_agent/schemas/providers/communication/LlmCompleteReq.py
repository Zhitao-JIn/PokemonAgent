"""文本补全请求（`LlmCompleteReq`）。

providers 是最底层共用层（调用方 brain，未来不排除其他模块），
按用户裁定豁免 From/To 标注——与 `LlmCompleteResp` / `VisionDescribe*` 同规则。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LlmCompleteReq(BaseModel):
    """一次纯文本补全请求。"""

    prompt: str = Field(description="完整 prompt 文本")
