"""`MemoryToolPort`：Harness 读写记忆的工具门面——情景 + 语义（object / knowledge）+ 跨局摘要。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.communication import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryKnowledgeResp,
)
from pokemon_agent.schemas.datastore import (
    EpisodeMemory,
    ObjectFactEvent,
    StepMemory,
)
from pokemon_agent.schemas.domain import PlaceInWorld


@runtime_checkable
class MemoryToolPort(Protocol):
    """Harness 读写记忆的接口：情景 + 语义（object / knowledge）+ 跨局摘要。"""

    # ---- 情景记忆（一条 = 一步） ----

    def query_episode_steps(self, episode_id: str) -> list[StepMemory]:
        """取这一局全部的单步情景记忆，按 step 升序。

        episode_id：这一局的标识。
        前置条件：episode_id 非空。
        后置条件：每条 entry.episode_id == episode_id；按 step 升序；不打分不截断。
        """
        ...

    def query_recent_steps(self, episode_id: str, limit: int) -> list[StepMemory]:
        """取这一局最近几条情景记忆，最新的在最后。

        episode_id：这一局的标识。
        limit：条数上限。
        前置条件：limit > 0。
        后置条件：条数 <= limit；全部来自该局。
        """
        ...

    def store_episode_step(self, entry: StepMemory) -> None:
        """写入一条情景记忆。

        entry：要写入的单步记忆。
        前置条件：entry.rationale 非空。
        """
        ...

    def discard_episode_steps(self, episode_id: str) -> None:
        """局结束后丢弃该局的单步记忆（step 记忆不跨 episode，蒸馏后无消费方）。"""
        ...

    # ---- 跨局摘要记忆（一条 = 一整局） ----

    def query_episode_summaries(
        self, scene: str, query: str, limit: int = 3, run_id: str = ""
    ) -> list[EpisodeMemory]:
        """检索和当前场景相关的跨局摘要记忆。

        scene：当前场景，非空。
        query：检索文本，非空。
        limit：条数上限。
        run_id：只检索**这一个 run** 里沉淀的摘要；空串 = 不限 run（仅测试用，
            生产调用方必须传——跨 run 的经验对当前 run 是"别人家的答案"，
            可能把失败局蒸馏出的"已验证"当真（跨 run 检索一律禁止）。
        前置条件：scene、query 非空；limit > 0。
        后置条件：条数 <= limit；按场景匹配 + 相关性 + 质量/成功排序。
        """
        ...

    @property
    def episode_summary_count(self) -> int:
        """库里有多少条跨局摘要记忆。"""
        ...

    def store_episode_summary(self, memory: EpisodeMemory) -> EpisodeMemory:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `Brain.verify_and_summarize()` 里完成（resp.episode_memory，
        见 ROADMAP 16），这个方法只做落盘 + 更新检索向量缓存。
        **这是这个 Port 上唯一的跨局摘要写入口**——只保留"先校验、
        再只用可信记录蒸馏"这一条路径，没有"不经校验全量蒸馏"的兜底入口。

        memory：组装好的摘要记忆。
        前置条件：memory.episode_id 非空。
        后置条件：返回原对象（落库后检索索引同步更新）。
        """
        ...

    # ---- 语义记忆（object 交互事件流） ----

    def query_object_events(
        self, map_id: int, before_step: int | None = None
    ) -> list[ObjectFactEvent]:
        """取这张地图上的全部交互事件，按 step 升序。

        map_id：地图编号。
        before_step：只取 step 严格小于它的事件；None = 不过滤（"检索不读未来"）。
        后置条件：没有记录返回空列表。
        """
        ...

    def query_object_events_at(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """取这一格的全部交互事件，按 step 升序（判定层的 kind 兜底查询）。

        place：要查的物体格。
        后置条件：没有记录返回空列表。
        """
        ...

    def append_object_events(self, events: list[ObjectFactEvent]) -> None:
        """追加一批交互事件（写穿：落盘与索引同时生效）。

        events：harness 判定层（`harness/object_interactions.py`）构造好的事件。
        前置条件：每个事件的 step ≥ 其所在局已有最大 step。
        """
        ...

    # ---- 语义记忆（知识库，和坐标无关的通用先验） ----

    def query_knowledge(self, req: FromHarnessToMemoryToolQueryKnowledgeReq) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从通用游戏先验里检索出和 req.query 相关的那几条。

        req：一次检索请求（检索文本 + 条数上限）。
        前置条件：req.query 非空；req.limit > 0。
        后置条件：返回 contents 和 sources；无命中时都是空列表。
        """
        ...
