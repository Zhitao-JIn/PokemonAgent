"""`memory` 段：召回条数、图片帽、混合检索参数与本地检索模型。"""

from pydantic import Field

from .base import Section


class MemoryConfig(Section):
    """记忆读取与检索的实验旋钮。

    `scope_image_cap` 是 L0 / L1 / run 蒸馏的图片上限（保留最新）；
    `rrf_k` 是 BM25 + 向量融合的平滑常数；
    融合候选数 `fuse_top_k = max(limit * fuse_multiplier, fuse_floor)`；
    两个模型名交给本地 fastembed。
    """

    recall_limit: int = Field(gt=0)
    scope_image_cap: int = Field(gt=0)
    rrf_k: int = Field(gt=0)
    fuse_multiplier: int = Field(gt=0)
    fuse_floor: int = Field(gt=0)
    embedding_model: str = Field(min_length=1)
    reranker_model: str = Field(min_length=1)
