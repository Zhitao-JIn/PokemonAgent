"""providers 包：具体 LLM / 视觉模型 / 向量化 / 重排模型的接入层。

模型 SDK 的直连只发生在这一层（铁律：业务代码不出现直连调用）。
`QwenProvider` 走 DashScope，`ArkProvider` 走火山方舟，两者同为
OpenAI 兼容协议；`FastEmbedText` / `FastEmbedReranker` 是本地向量化与重排。

本文件是统一出口：消费方只写 `from pokemon_agent.providers import X`，
不深到模块文件。
"""

__all__ = [
    "ArkProvider",
    "FastEmbedReranker",
    "FastEmbedText",
    "QwenProvider",
]
from .local_embedding import FastEmbedText
from .local_reranker import FastEmbedReranker
from .openai_compatible import ArkProvider, QwenProvider
