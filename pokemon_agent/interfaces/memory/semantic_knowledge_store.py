"""语义记忆（knowledge）的存储接口：和坐标无关的通用先验。

**只读**——内容是运营手动维护的 `.md` 文件，不是 agent 跑的过程中自动积累
出来的，所以只有读端，没有 Writer（与 `SemanticObjectStore` / `EpisodeMemoryStore`
的读写并集不同）。和 `SemanticObjectStore`（interfaces/memory/semantic_object_store.py）
同层对称：都是可注入的存储后端，`MemoryTool` 构造时注入。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SemanticKnowledgeStore(Protocol):
    """语义记忆（knowledge）的读端。"""

    def chunks(self) -> list[tuple[str, str]]:
        """一次读盘返回 `[(文件名, 正文)]`，只含非空 md，按文件名排序。

        文件名是检索结果展示层的来源引用；正文是检索单元。
        后置条件：目录为空或全空文件时返回空列表——调用方据此知道"没有知识可检索"。
        """
        ...

    def mtime(self) -> float:
        """目录下最新 md 的修改时间；没有文件时返回 0.0。"""
        ...
