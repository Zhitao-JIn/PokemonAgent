"""providers/interface 包统一出口：四个提供方协议（`LLMProvider`/`VisionProvider`
/`JudgeProvider`/`EmbeddingProvider`/`RerankerProvider`）+ 数据形状（`ModelCall`）。

都只依赖 `schemas.providers`（信封类型），不依赖任何重实现（`fastembed`/PIL/
真的网络调用都在各自实现文件内部懒加载或按需 import），可以放心立即加载，
不需要 `world/interface` 那种懒加载。
"""

from __future__ import annotations

from .domain import ModelCall
from .embedding_provider import EmbeddingProvider
from .llm_provider import LLMProvider
from .reranker_provider import RerankerProvider
from .vision_provider import JudgeProvider, VisionProvider

__all__ = [
    "EmbeddingProvider",
    "JudgeProvider",
    "LLMProvider",
    "ModelCall",
    "RerankerProvider",
    "VisionProvider",
]
