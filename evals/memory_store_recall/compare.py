"""检索分数的纯比较规则，与旧查询级均值口径一致。"""


def retrieval_metrics(ranked: list[str], relevant: list[str], k: int) -> tuple[float, float]:
    """recall@k 分母是全部相关记录，MRR 取前 k 条的第一条相关记录倒数。"""
    hits = set(ranked[:k]) & set(relevant)
    first = next((index for index, item in enumerate(ranked[:k], 1) if item in relevant), None)
    return len(hits) / len(set(relevant)), 1 / first if first else 0.0
