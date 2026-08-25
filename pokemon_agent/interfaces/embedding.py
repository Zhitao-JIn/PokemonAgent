"""Embedding 提供方接口。

存在的意义和 `interfaces/llm.py` 一样：**任何地方都不许直连模型 SDK/权重库**
（CLAUDE.md 第六节）——`memory/retrieval.py` 只认这个 Protocol，不知道背后是
`fastembed`、真远程 embedding 服务、还是测试里的假实现。换后端只改装配处一行。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """把一批文本变成向量。故意做得很薄——和 `LLMProvider` 同样的理由：

    - **批量而不是逐条**：`embed(texts)` 一次收一批，不是 `embed_one(text)`
      调 N 次——真实的本地/远程 embedding 模型批量推理远比逐条快，接口形状
      应该鼓励调用方一次性把要算的文本收集齐再调用，而不是在循环里调。
    - **不做缓存**：同一段文本被反复 embed 是调用方的事（比如知识库那边按
      mtime 判断要不要重算，见 `tools/memory_tool.py`），这一层只管"给文本、
      吐向量"，不猜"这段文本是不是已经算过"。
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把 `texts` 逐条变成向量，返回值与 `texts` 等长、顺序一致。

        前置条件：`texts` 非空，且其中每条文本非空——空字符串没有语义，
            让调用方在传进来之前就过滤掉，这一层不该替调用方做这个判断。
        后置条件：返回的每个向量维度相同（同一个模型的输出天然如此）；
            不保证向量是单位向量——是否归一化是具体实现的选择，
            `memory/retrieval.py` 的余弦相似度计算不依赖这一点。
        失败：底层模型不可用（例如权重还没下载好、推理进程崩了）时抛异常，
            不返回空列表或全零向量——"没算出向量"和"算出的向量恰好是这个值"
            必须能被调用方区分开。

        把每段文本变成一个向量，顺序与输入一致。
        """
        ...
