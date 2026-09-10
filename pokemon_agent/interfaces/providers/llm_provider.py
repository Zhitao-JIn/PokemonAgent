"""LLM 提供方接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.providers import LlmCompleteReq, LlmCompleteResp


@runtime_checkable
class LLMProvider(Protocol):
    """纯文本模型的出口。"""

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        """调用文本模型，返回一次补全。

        前置条件：req.prompt 非空。
        后置条件：返回的 text 可能是任意字符串（含不合法 JSON），格式由调用方负责。
        失败：底层不可用时抛异常，不返回空 LlmCompleteResp。
        """
        ...
