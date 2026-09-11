"""providers 包：具体 LLM / 视觉模型 / 向量化 / 重排模型的接入层。

- `interface/`：这个模块自己的港口 + 数据 schema——`LLMProvider`/
  `VisionProvider`/`JudgeProvider`/`EmbeddingProvider`/`RerankerProvider`
  五个协议，外加 `ModelCall`（一次模型调用留下的账）。原来分别放在顶层
  `interfaces/providers/` 和 `schemas/providers/domain/`，这次一起搬进来，
  跟实现同住一包（`pokemon_agent/interfaces/` 这次整个撤销，不保留
  re-export 薄壳）。
- 模型 SDK 的直连只发生在实现文件这一层（铁律：业务代码不出现直连调用）。
  `QwenProvider` 走 DashScope，`ArkProvider` 走火山方舟，`DeepSeekProvider`
  走 DeepSeek 官方 API，三者同为 OpenAI 兼容协议；`FastEmbedText` /
  `FastEmbedReranker` 是本地向量化与重排。

本文件是统一出口：消费方只写 `from pokemon_agent.providers import X`，
不深到模块文件。
"""

__all__ = [
    "ArkProvider",
    "DeepSeekProvider",
    "EmbeddingProvider",
    "FastEmbedReranker",
    "FastEmbedText",
    "JudgeProvider",
    "LLMProvider",
    "ModelCall",
    "QwenProvider",
    "RerankerProvider",
    "VisionProvider",
]
from .interface import (
    EmbeddingProvider,
    JudgeProvider,
    LLMProvider,
    ModelCall,
    RerankerProvider,
    VisionProvider,
)
from .local_embedding import FastEmbedText
from .local_reranker import FastEmbedReranker
from .openai_compatible import ArkProvider, DeepSeekProvider, QwenProvider
