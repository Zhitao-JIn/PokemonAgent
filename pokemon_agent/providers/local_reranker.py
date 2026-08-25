"""`RerankerPort` 的本地实现：fastembed 跑一个交叉编码器给候选精排。

混合检索的最后一段。前两段（BM25 + 向量）各自便宜但都只看"像不像"，
交叉编码器把查询和候选拼在一起真读一遍，贵得多，所以**只对前几条跑**。

**模型延迟加载**：构造时只记下名字，第一次真要用才把权重拉下来。
装配发生在进程启动时，而很多次运行（跑测试、看帮助、跑不带检索的路径）
根本用不到它——为它无条件等一次下载不划算。
"""

from __future__ import annotations


class FastEmbedReranker:
    """`RerankerProvider` 的实现，模型固定用 `BAAI/bge-reranker-base`
    （`fastembed` 内置支持、对中文效果不错的 cross-encoder 精排模型）。

    懒加载，理由同 `FastEmbedText`。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        """记下模型名，**先不加载**。"""
        self._model_name = model_name
        self._model = None

    def _ensure_loaded(self):
        """第一次真要用的时候才把模型载进来。"""
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(model_name=self._model_name)
        return self._model

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """给每条候选打一个相对查询的相关性分。"""
        assert query, "rerank() needs a non-empty query"
        assert documents, "rerank() needs at least one document"
        assert all(d for d in documents), "rerank() got an empty string in documents"
        model = self._ensure_loaded()
        return [float(s) for s in model.rerank(query, documents)]

    def config(self) -> dict[str, str]:
        """自报模型与运行时，进 manifest 用。"""
        return {"model": self._model_name, "runtime": "fastembed"}
