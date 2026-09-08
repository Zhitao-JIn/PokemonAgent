"""情景记忆（episodic）的存储接口：这一局做过什么。

**只存只取，不做检索、不调模型。** 检索算法（混合检索 + 加权排序）在
`MemoryTool` 里，蒸馏与组装都在 `Brain.verify_and_summarize()` 里——store 只负责
「StepMemory 按局存取」和「EpisodeMemory 全量存取」这两件事。
和 `SemanticObjectStore`（interfaces/memory/semantic_object.py）同层对称：
都是可注入的存储后端，`MemoryTool` 构造时注入。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.datastore import EpisodeMemory, StepMemory


@runtime_checkable
class EpisodeMemoryReader(Protocol):
    """情景记忆（episodic）的读端。"""

    def query_episode_steps(self, episode_id: str) -> list[StepMemory]:
        """取这一局全部的单步情景记忆，按 step 升序。

        episode_id：局号。
        后置条件：按 `step` 升序；没有记录返回空列表。
        """
        ...

    def query_recent_steps(self, episode_id: str, limit: int) -> list[StepMemory]:
        """取这一局最近几条情景记忆。

        episode_id：局号。
        limit：条数上限。
        前置条件：limit > 0。
        """
        ...

    def all_episode_summaries(self) -> list[EpisodeMemory]:
        """取全部跨局摘要记忆，未排序。

        检索（场景过滤 + 相关性排序）是 `MemoryTool` 的活，这里只把
        全部摘要交出去当检索原料。
        """
        ...

    def episode_summary_count(self) -> int:
        """库里有多少条跨局摘要记忆。"""
        ...


@runtime_checkable
class EpisodeMemoryWriter(Protocol):
    """情景记忆（episodic）的写端。"""

    def store_episode_step(self, entry: StepMemory) -> None:
        """写入一条单步情景记忆。

        entry：一步的记忆，`episode_id` 已由 Harness 盖章。
        前置条件：entry.rationale 非空。
        """
        ...

    def store_episode_summary(self, memory: EpisodeMemory) -> None:
        """写入一条跨局摘要记忆。

        memory：蒸馏好的摘要。**蒸馏本身不在这里**——`MemoryTool` 调
        `Brain.verify_and_summarize()` 组装好之后才交进来落库。
        """
        ...

    def discard_episode_steps(self, episode_id: str) -> None:
        """局结束后丢弃该局的单步记忆（step 记忆不跨 episode）。

        episode_id：要丢弃的局号。
        后置条件：该局的单步记忆不再可查；未知局号静默无操作。
        """
        ...


@runtime_checkable
class EpisodeMemoryStore(EpisodeMemoryReader, EpisodeMemoryWriter, Protocol):
    """情景记忆（episodic）存储的并集。"""
