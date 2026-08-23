"""本地 embedding provider：`fastembed`（ONNX runtime 推理，不需要 torch）。

**这个文件和 `providers/dashscope.py` 是仅有的两处直连模型的地方**——那边连的是
远程 API（HTTP），这里连的是本地跑的权重（`fastembed` 首次用某个模型名时从
HuggingFace Hub 下一次，之后离线复用，不再需要网络）。选本地而不是接一个远程
embedding API：检索发生在每一步的 `retrieve_memory` 节点里，接远程服务意味着
每次决策前都要多等一次网络往返、多花一份调用成本，而 embedding 本身不需要
"越大越好"的模型能力（不是生成任务），本地小模型的精度已经够用。

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
    `EpisodeMemoryGenerator`/测试这类不一定每次都会真正调用 embedding 的场景。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self._model_name = model_name
        self._model = None  # 懒加载，见类文档

    def _ensure_loaded(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts, "embed() needs at least one text"
        assert all(t for t in texts), "embed() got an empty string in texts"
        model = self._ensure_loaded()
        return [vec.tolist() for vec in model.embed(texts)]
