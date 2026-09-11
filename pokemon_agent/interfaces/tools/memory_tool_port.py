"""`MemoryToolPort`：Harness 读写记忆的工具门面——情景 + 语义（object / knowledge）+ 跨局摘要。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolAppendObjectEventsReq,
    FromHarnessToMemoryToolQueryEpisodeStepsReq,
    FromHarnessToMemoryToolQueryEpisodeStepsResp,
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryEpisodeSummariesResp,
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryKnowledgeResp,
    FromHarnessToMemoryToolQueryObjectEventsAtReq,
    FromHarnessToMemoryToolQueryObjectEventsAtResp,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToMemoryToolQueryObjectEventsResp,
    FromHarnessToMemoryToolQueryRecentStepsReq,
    FromHarnessToMemoryToolQueryRecentStepsResp,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryResp,
    FromHarnessToMemoryToolVoidMemoryAfterReq,
    FromHarnessToMemoryToolVoidMemoryAfterResp,
)


@runtime_checkable
class MemoryToolPort(Protocol):
    """Harness 读写记忆的接口：情景 + 语义（object / knowledge）+ 跨局摘要。

    这是第一跳（harness → 门面），入参与返回一律是信封；门面往里调各个
    store 走裸参数、返回 store 自己的类型，那一跳不造信封。
    """

    # ---- 情景记忆（一条 = 一步） ----

    def query_episode_steps(
        self, req: FromHarnessToMemoryToolQueryEpisodeStepsReq
    ) -> FromHarnessToMemoryToolQueryEpisodeStepsResp:
        """取这一局全部的单步情景记忆，按 step 升序。

        req.episode_id：这一局的标识。
        前置条件：req.episode_id 非空。
        后置条件：每条 entry.episode_id == req.episode_id；按 step 升序；不打分不截断。
        """
        ...

    def query_recent_steps(
        self, req: FromHarnessToMemoryToolQueryRecentStepsReq
    ) -> FromHarnessToMemoryToolQueryRecentStepsResp:
        """取这一局最近几条情景记忆，最新的在最后。

        req.episode_id：这一局的标识。
        req.limit：条数上限。
        前置条件：req.limit > 0。
        后置条件：条数 <= req.limit；全部来自该局。
        """
        ...

    def store_episode_step(self, req: FromHarnessToMemoryToolStoreEpisodeStepReq) -> None:
        """写入一条情景记忆。

        req.entry：要写入的单步记忆。
        前置条件：req.entry.rationale 非空。
        """
        ...

    # ---- 跨局摘要记忆（一条 = 一整局） ----

    def query_episode_summaries(
        self, req: FromHarnessToMemoryToolQueryEpisodeSummariesReq
    ) -> FromHarnessToMemoryToolQueryEpisodeSummariesResp:
        """检索和当前场景相关的跨局摘要记忆。

        req.scene：当前场景，非空。
        req.query：检索文本，非空。
        req.limit：条数上限。
        req.run_id：只检索**这一个 run** 里沉淀的摘要；空串 = 不限 run（仅测试用，
            生产调用方必须传——跨 run 的经验对当前 run 是"别人家的答案"，
            可能把失败局蒸馏出的"已验证"当真（跨 run 检索一律禁止）。
        前置条件：req.scene、req.query 非空；req.limit > 0。
        后置条件：条数 <= req.limit；按场景匹配 + 相关性 + 质量/成功排序。
        """
        ...

    def store_episode_summary(
        self, req: FromHarnessToMemoryToolStoreEpisodeSummaryReq
    ) -> FromHarnessToMemoryToolStoreEpisodeSummaryResp:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `Brain.verify_and_summarize()` 里完成（resp.episode_memory，
        见 ROADMAP 16），这个方法只做落盘 + 更新检索向量缓存。
        **这是这个 Port 上唯一的跨局摘要写入口**——只保留"先校验、
        再只用可信记录蒸馏"这一条路径，没有"不经校验全量蒸馏"的兜底入口。

        req.memory：组装好的摘要记忆。
        前置条件：req.memory.episode_id 非空。
        后置条件：resp.memory 是原对象（落库后检索索引同步更新）。
        """
        ...

    # ---- 语义记忆（object 交互事件流） ----

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        """取这张地图上的全部交互事件，按 step 升序。

        req.map_id：地图编号。
        req.before_step：只取 step 严格小于它的事件；None = 不过滤（"检索不读未来"）。
        后置条件：没有记录返回空列表。
        """
        ...

    def query_object_events_at(
        self, req: FromHarnessToMemoryToolQueryObjectEventsAtReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsAtResp:
        """取这一格的全部交互事件，按 step 升序（判定层的 kind 兜底查询）。

        req.place：要查的物体格。
        后置条件：没有记录返回空列表。
        """
        ...

    def append_object_events(self, req: FromHarnessToMemoryToolAppendObjectEventsReq) -> None:
        """追加一批交互事件（写穿：落盘与索引同时生效）。

        req.events：harness 判定层（`harness/object_interactions.py`）构造好的事件。
        前置条件：每个事件的 step ≥ 其所在局已有最大 step。
        """
        ...

    # ---- 语义记忆（知识库，和坐标无关的通用先验） ----

    def query_knowledge(
        self, req: FromHarnessToMemoryToolQueryKnowledgeReq
    ) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从通用游戏先验里检索出和 req.query 相关的那几条。

        req：一次检索请求（检索文本 + 条数上限）。
        前置条件：req.query 非空；req.limit > 0。
        后置条件：返回 contents 和 sources；无命中时都是空列表。
        """
        ...

    def void_memory_after(
        self, req: FromHarnessToMemoryToolVoidMemoryAfterReq
    ) -> FromHarnessToMemoryToolVoidMemoryAfterResp:
        """把一局 `req.step` 之后不再成立的单步记忆与 object 事件**归档**（checkpoint 恢复）。

        圈定哪些记录作废由本层（tool）算：harness 只给游标语义（`episode_id` +
        `step`），"哪些记录落在游标之后"是 tool 的领域知识。该局的跨局摘要也
        一并归档——它是局收尾的产物，而收尾总在该局最后一个 checkpoint 之后
        （漏了它重跑会落下第二条同 `episode_id` 的摘要）。

        前置条件：req.step ≥ -1（-1 = 整局废弃）；req.episode_id 已存在或为空局。
        后置条件：该局内 step > req.step 的单步记忆与 object 事件、以及该局全部
            跨局摘要，全部不可再查（文件搬进 `memory/voided-<ts>/` 留档，不删除）；
            resp.removed 是各类被归档的条数。
        """
        ...
