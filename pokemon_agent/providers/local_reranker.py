"""本地 reranker provider：`fastembed`（同一个库，既做 embedding 也做 rerank，
见 `providers/local_embedding.py` 顶部选它的理由——ONNX runtime，不需要 torch）。
"""

from __future__ import annotations


class FastEmbedReranker:
    """`RerankerProvider` 的实现，模型固定用 `BAAI/bge-reranker-base`
    （`fastembed` 内置支持、对中文效果不错的 cross-encoder 精排模型）。

    懒加载，理由同 `FastEmbedText`。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        self._model_name = model_name
        self._model = None

    def _ensure_loaded(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(model_name=self._model_name)
        return self._model

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        assert query, "rerank() needs a non-empty query"
        assert documents, "rerank() needs at least one document"
        assert all(d for d in documents), "rerank() got an empty string in documents"
        model = self._ensure_loaded()
        return [float(s) for s in model.rerank(query, documents)]
