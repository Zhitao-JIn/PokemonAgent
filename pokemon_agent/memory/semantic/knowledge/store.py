"""语义知识库——项目自己攒的、和具体坐标无关的通用游戏先验。

和 `memory/semantic/object_store.py` 的区别：那边记的是"这一格东西是什么、
互动过没有"，是 agent 自己在这一局/跨局探索出来的，天然按坐标索引；这里放的
是不需要探索、写死就对的游戏机制常识（比如"草丛要多走几步才会遇到野生
宝可梦，可以连按走到草丛尽头，不用一格一格试"、"水系克制火系"这类攻略型知识）
——这类知识不属于任何一格，agent 每一局开局就该知道，不该靠它自己撞几十次墙
才总结出来。

存成 `.md` 而不是 Python 字符串常量：这些是要**运营/迭代**的内容——加一条新的
游戏机制先验，应该是加一个 `.md` 文件或者编辑一段文字，而不是改代码。

## 检索策略：按文件作为检索单元

**这条规则已经变了**——早先"全部读入"的判断，是在知识库只有少量内容时下的。
现在每个 `.md` 文件是一个独立知识 chunk，交给 `MemoryTool` 用和跨局摘要记忆一样
的混合检索（见 `memory/retrieval.py`）按需挑出相关文件，而不是整座知识库照单全收。

`load_all()` 留着没删，供需要整合知识库文本的调用方使用；`load_chunks()` 保留
文件边界，避免把不同主题的 markdown 拼成一个检索单元。
"""

from __future__ import annotations

import pathlib

_DIR = pathlib.Path(__file__).parent


def load_all() -> str:
    """把这个目录下所有 `.md` 文件的内容原样拼起来，按文件名排序（确定性）。

    后置条件：目录下没有任何 `.md` 文件时返回空串。
    """
    files = sorted(p for p in _DIR.glob("*.md"))
    return "\n\n".join(f.read_text(encoding="utf-8").strip() for f in files)


def load_chunks() -> list[str]:
    """把每个非空 `.md` 文件作为一个独立 chunk，按文件名确定顺序。

    不在文件内部按段落拆分：同一文件中的标题、说明和例子共同构成一个知识主题，
    保留在同一个检索单元里，避免召回段落时丢失上下文。

    后置条件：目录下没有任何 `.md` 文件、或全部文件都是空文件时返回空列表——
        调用方（`MemoryTool.knowledge_base`）据此知道"没有知识可检索"，
        不必特殊处理"检索了但库是空的"这种情况，两者应该是同一件事。
    """
    files = sorted(p for p in _DIR.glob("*.md"))
    return [text for f in files if (text := f.read_text(encoding="utf-8").strip())]


def load_named_chunks() -> list[tuple[str, str]]:
    """加载 `(文件名, 正文)`，供检索结果的展示层引用来源文件。"""
    return [
        (f.name, text)
        for f in sorted(_DIR.glob("*.md"))
        if (text := f.read_text(encoding="utf-8").strip())
    ]


def mtime() -> float:
    """知识库目录下全部 `.md` 文件里最新的修改时间；没有文件时返回 0.0。

    `MemoryTool` 用它判断"要不要重新算一遍知识片段的 embedding"——
        embedding 现算一次有成本，但知识库内容会被运营编辑，值得按"文件有没有变过"
        决定要不要重新读取文件并重算 embedding，
    见 `MemoryTool.knowledge_base` 的说明。
    """
    files = list(_DIR.glob("*.md"))
    if not files:
        return 0.0
    return max(f.stat().st_mtime for f in files)
