"""本地 embedding provider：`fastembed`（ONNX runtime 推理，不需要 torch）。

**它在 memory 包里的位置**（0913 定案）：这个类和 `fastembed_reranker.py` 是
`EmbeddingProvider`/`RerankerProvider` 两个协议的**唯一实现**，而这两个协议的
消费者只有 memory 的检索链路（`retrieval.py::embedding_rank` 与 reranker 精排）。
协议挨着实现——跟 `MemoryStorePort` 同住一包，**拷走 `memory/` 就拿到完整可复用的
一块**。它们原来住在顶层 `pokemon_agent/providers/`（那个包 0913 整个解散：
`openai_compatible.py` 搬进 `brain/providers.py`，这两个文件搬进这里）。

**它跟模型服务直连没有关系**：`brain/providers.py` 连的是远程 API（HTTP），
这里连的是本地跑的权重（`fastembed` 首次用某个模型名时从 HuggingFace Hub
下一次，之后离线复用，不再需要网络）。选本地而不是接一个远程 embedding API：
检索发生在每一步的 `retrieve_memory` 节点里，接远程服务意味着每次决策前都要
多等一次网络往返、多花一份调用成本，而 embedding 本身不需要"越大越好"的模型
能力（不是生成任务），本地小模型的精度已经够用。

选 `fastembed` 而不是 `sentence-transformers`：两者都能跑 embedding，
但 `sentence-transformers` 依赖 `torch`——几百 MB 到一 GB 的框架，只为了跑
几十 MB 的小模型推理，代价不成比例；`fastembed` 底层是 ONNX runtime，
同样的模型精度、依赖体积小一个数量级。
"""

from __future__ import annotations


class FastEmbedText:
    """`EmbeddingProvider` 的实现，模型固定用 `BAAI/bge-small-zh-v1.5`
    （中文优化、约 95MB，`fastembed` 内置支持的模型列表之一）。

    模型在**首次调用 `embed()` 时才加载**（懒加载，不在 `__init__` 里就下载/
    加载权重）——构造这个 provider 的代价应该只是"记下要用哪个模型"，
    不该在装配阶段（`build.py`）就付一次模型加载的时间，尤其是像
    测试这类不一定每次都会真正调用 embedding 的场景。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        """记下模型名，**先不加载**。"""
        self._model_name = model_name
        self._model = None  # 懒加载，见类文档

    def _ensure_loaded(self) -> object:
        """第一次真要用的时候才把模型载进来。"""
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把每段文本变成一个向量，顺序与输入一致。"""
        assert texts, "embed() needs at least one text"
        assert all(t for t in texts), "embed() got an empty string in texts"
        model = self._ensure_loaded()
        return [vec.tolist() for vec in model.embed(texts)]

    def config(self) -> dict[str, str]:
        """自报模型与运行时，进 manifest 用。"""
        return {"model": self._model_name, "runtime": "fastembed"}
