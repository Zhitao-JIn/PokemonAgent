"""轻量向量相似度：字符 bigram TF-IDF + 余弦相似度。**纯函数，不碰任何存储状态**——

和 `memory/util.py` 拆开的理由一样：这几个函数可以脱离"库里现在有哪些记忆"
单独测试，也不该知道调用方是在查跨局摘要记忆还是别的什么。

## 为什么是字符 bigram，不是分词

项目里的文本是中文，标准库没有分词器（CLAUDE.md 第六节：这个阶段零新增依赖）。
`MemoryTool._overlap`（单步情景记忆用的那套）已经把"字符"当 token 用了——
`set(query) & set(content)`，逐字符比较。直接沿用单字符会有个问题：
"进" 和 "退" 各自出现在"前进"和"后退"里，单字符集合看不出这是两个不相关的词，
两个字符各自的出现频率把它们错误地拉近。两个字符一组的 bigram
（"前进"→{"前进"}，"进入"→{"进入"}）能多留住一点词序信息，
且实现代价几乎为零——仍然不需要任何分词库。

## 为什么现算，不缓存

corpus（当前候选记忆的全部文本）随每次写入变化，条目量级还是个位数到
几十条——现算一次 TF-IDF 的成本远低于维护一份"什么时候该失效"的缓存，
和 `memory/semantic/knowledge/store.py` 的 `load_all()` 不缓存是同一个理由。
等条目量级真的涨到"现算太贵"的地步，再考虑要不要缓存，现在不为这个还没
到来的问题预留复杂接口。
"""

from __future__ import annotations

import math

Vector = dict[str, float]


def tokenize(text: str) -> list[str]:
    """把文本切成字符 bigram（两个相邻非空白字符一组）。

    后置条件：非空白字符数 < 2 时退化成单字符 token（不然短文本会被切成空列表，
        `cosine_similarity` 对空向量的处理是返回 0，短查询就会永远查不中任何东西——
        那不是"不相关"，是这个函数偷懒的产物，必须避免）。
    """
    chars = [c for c in text if not c.isspace()]
    if len(chars) < 2:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def build_idf(corpus: list[str]) -> dict[str, float]:
    """给一批文档算每个 bigram 的逆文档频率（平滑过的版本，值域 (0, +∞)）。

    用的是标准的平滑 idf：`log((N+1)/(df+1)) + 1`——分子分母各加一，
    是为了 `df == N`（这个 bigram 每篇文档都出现，比如高频虚词）时
    权重仍然大于 0 而不是变成 `log(1) == 0`，把这个 bigram 从向量里整个抹掉；
    末尾 `+ 1` 是为了 `df` 很大时权重仍然有个非零下限，不会被压成可以忽略的小数。

    后置条件：`corpus` 为空返回空 dict——调用方（`tfidf_vector`）据此知道
        "还没有语料"，所有 bigram 都走默认权重。
    """
    n = len(corpus)
    if n == 0:
        return {}
    doc_freq: dict[str, int] = {}
    for doc in corpus:
        for term in set(tokenize(doc)):
            doc_freq[term] = doc_freq.get(term, 0) + 1
    return {term: math.log((n + 1) / (df + 1)) + 1 for term, df in doc_freq.items()}


def tfidf_vector(text: str, idf: dict[str, float]) -> Vector:
    """把一段文本变成一个 TF-IDF 向量（稀疏，只存非零维度）。

    `idf` 里查不到的 bigram（语料里没见过——通常是查询词带进来的新词）
    用 `log(2) + 1` 兜底，约等于"只在一篇文档里出现过"的 idf，
    不给未知词额外的权重优势，也不让它直接被当成 0 权重抹掉。
    """
    tokens = tokenize(text)
    if not tokens:
        return {}
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    n = len(tokens)
    fallback_idf = math.log(2) + 1
    return {t: (count / n) * idf.get(t, fallback_idf) for t, count in tf.items()}


def cosine_similarity(a: Vector, b: Vector) -> float:
    """两个稀疏向量的余弦相似度，值域 [0, 1]（TF-IDF 权重恒非负，不会到负区间）。

    后置条件：任一向量为空（文本为空、或全是被 `tokenize` 过滤掉的空白）时返回 0.0，
        不抛异常——"这段文本没有内容"不该让排序流程崩掉，是"不相关"的一种表达。
    """
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
