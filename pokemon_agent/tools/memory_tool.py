"""`MemoryToolPort` 的实现：Harness 和四类记忆之间那层壳。**不碰世界。**

四类记忆在这里汇合，但读写语义各不相同：

    单步情景记忆    这一局做过什么      全量返回，不排序不截断
    语义记忆 object  那一格上有什么东西  按坐标查
    知识库          和坐标无关的先验    混合检索（BM25 + 向量 + reranker）
    跨局摘要        别的局蒸馏的经验    场景硬过滤 + 混合检索

**混合检索的两路分数要先各自归一化再加权**：BM25 的分无上界，向量余弦在 [-1,1]，
直接相加等于让 BM25 独裁。

**知识库按文件 mtime 增量重建索引**，不是每次查询都重新 embed——那会让每一步决策
都多等几百毫秒。代价是改完文件要等一次 mtime 变化才生效，但这正好支持
"一边跑 episode 一边改 `memory/semantic/knowledge/*.md`"。

方法上挂着权限装饰器，所以除各自写明的失败外都可能抛权限异常。
更多设计记录见 `docs/spec/memory/SPEC.md`。
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_permission import require_permission

from pokemon_agent.interfaces import (
    EmbeddingProvider,
    EpisodeMemoryStore,
    RerankerProvider,
    SemanticKnowledgeStore,
    SemanticObjectStore,
)
from pokemon_agent.memory import (
    EventObjectStore,
    FileEpisodeMemoryStore,
    KnowledgeStore,
    hybrid_retrieve,
)
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

# 跨局摘要记忆 / 知识库排序：混合检索（关键词 BM25 + 向量 + reranker 精排，见
# `memory/retrieval.py`）给出的 reranker 分数是"文本相关性"这一项，值域没有
# 自然的上下界（cross-encoder 输出的是未经归一化的 logits），所以每次查询后
# 现算 min-max 归一化到 [0, 1] 再叠加权重——不能直接拿 reranker 的原始分数
# 和质量分/成败这些本来就在 [0, 1] 或布尔量级的信号相加，量纲对不上。
# 权重比例：相关性最重要（"这条经验到底切不切题"），
# 质量/成功用来在相关性接近时挑更可信的那条，不该反过来压过相关性。
EPISODE_RELEVANCE_WEIGHT = 10.0
EPISODE_QUALITY_WEIGHT = 3.0
EPISODE_SUCCESS_WEIGHT = 1.5

# 混合检索粗筛阶段留几个候选给 reranker 精排——比 `limit` 大一截，给 reranker
# 留出"重新排出比粗筛更准的顺序"的空间；候选集本来就小于这个数时，
# `hybrid_retrieve` 会自动只处理实际有的那些，不会因为要凑数而出错。
EPISODE_FUSE_TOP_K = 10
KNOWLEDGE_FUSE_TOP_K = 10

EPISODE_CANDIDATE_CAP = 20
"""跨局摘要检索的**候选上限**：场景匹配后超过这个数，先按质量分粗筛到前
`EPISODE_CANDIDATE_CAP` 条再进混合检索。

经验库有上限（`max_summaries`）但仍可能攒到几十上百条——候选全量进检索的话，
每步决策都要对全部候选做 BM25 + 向量 + reranker，纯属浪费。质量分是现成的
粗筛信号（`quality_score`），先砍掉最差的再精排。"""


def _normalize(scores: list[float]) -> list[float]:
    """min-max 归一化到 [0, 1]。全部并列（`max == min`）时统一给 1.0——
    这种情况下没有相关性上的高低之分，不该被除零判成全部是 0（那样会让
    质量/成功权重在"文本同样相关"的场景里反而失去区分度）。

    把一组分数压到 [0, 1]。
    """
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有单步情景记忆、跨局摘要记忆、
    语义记忆（object + knowledge）存储。
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
        objects: SemanticObjectStore | None = None,
        episodes: EpisodeMemoryStore | None = None,
        knowledge: SemanticKnowledgeStore | None = None,
    ) -> None:
        """接好四类记忆的后端，备好检索器与索引缓存。

        `objects` / `episodes` / `knowledge` 是**可注入的存储后端**——默认实现
        （object 走内存、跨局摘要落盘 md + frontmatter、知识库读 `semantic/knowledge/`
        目录）；测试换 mock，都只动构造参数，`MemoryTool` 不认实现、只认接口
        （`SemanticObjectStore` / `EpisodeMemoryStore` / `SemanticKnowledgeStore`）。
        """
        self._episodes: EpisodeMemoryStore = episodes or FileEpisodeMemoryStore()
        self._episode_memory_vectors: dict[str, list[float]] = {}
        """`episode_id → embedding`，**写入时算好、缓存住**——查询时只用现算
        `query` 自己的向量，不用每次检索都把全部候选重新 embed 一遍。
        """
        self._objects: SemanticObjectStore = objects or EventObjectStore()
        self._knowledge: SemanticKnowledgeStore = knowledge or KnowledgeStore()
        self._embedding = embedding_provider
        self._reranker = reranker_provider
        self._knowledge_chunks: list[str] = []
        self._knowledge_names: list[str] = []
        self._knowledge_vectors: list[list[float]] = []
        self._knowledge_mtime: float = -1.0
        """哨兵值：任何真实 mtime 都 ≥ 0，第一次 `knowledge_base()` 调用
        一定会命中"和缓存不一致"从而触发首次加载。
        """

    # ---- 情景记忆：episodic（单步，全量，不检索） ----

    @require_permission("read:memory:episodic")
    def query_episode_steps(self, episode_id: str) -> list[StepMemory]:
        """取这一局全部的单步情景记忆，按 step 升序。"""
        return self._episodes.query_episode_steps(episode_id)

    @require_permission("read:memory:episodic")
    def query_recent_steps(self, episode_id: str, limit: int) -> list[StepMemory]:
        """取这一局最近几条情景记忆。"""
        return self._episodes.query_recent_steps(episode_id, limit)

    @require_permission("write:memory:episodic")
    def store_episode_step(self, entry: StepMemory) -> None:
        """写入一条情景记忆。"""
        self._episodes.store_episode_step(entry)

    @require_permission("delete:memory:episodic")
    def discard_episode_steps(self, episode_id: str) -> None:
        """局结束后丢弃该局的单步记忆（蒸馏后无消费方，不跨局累积）。"""
        self._episodes.discard_episode_steps(episode_id)

    # ---- 跨局摘要记忆：episode memory（混合检索） ----

    @require_permission("read:memory:episode")
    def query_episode_summaries(
        self, scene: str, query: str, limit: int = 3, run_id: str = ""
    ) -> list[EpisodeMemory]:
        """场景硬过滤（含通配，见 `EpisodeMemory.matches_scene`）之后，
        用混合检索（BM25 + 向量 + reranker）排出"文本相关性"，
        再叠加质量分和是否成功两个信号，取前 `limit` 条。

        先按场景硬过滤，再按相关性挑出前几条跨局经验。

        `run_id` 非空时只检索该 run 沉淀的摘要——禁止跨 run 检索，失败局
        蒸馏出的"已验证"经验一旦被当真就污染决策（取舍见 `CHANGELOG.md`
        2026-09-03 条目；`episode_harness` 传 `self._run_id`）。
        """
        assert scene, "query_episode_summaries() needs a non-empty scene"
        assert limit > 0, f"limit must be > 0, got {limit}"
        candidates = [
            m
            for m in self._episodes.all_episode_summaries()
            if m.matches_scene(scene) and (not run_id or m.run_id == run_id)
        ]
        if not candidates:
            return []
        # 候选上限：超过就按质量分粗筛（经验库的价值是高质量可复用经验，
        # 质量最低的先出局——精排本来也会把低质量排后面，粗筛只是省掉白做）。
        if len(candidates) > EPISODE_CANDIDATE_CAP:
            candidates.sort(key=lambda m: m.quality_score, reverse=True)
            candidates = candidates[:EPISODE_CANDIDATE_CAP]

        documents = [m.render() for m in candidates]
        vectors = [self._episode_vector(m) for m in candidates]
        fuse_top_k = max(limit * 3, EPISODE_FUSE_TOP_K)
        results = hybrid_retrieve(
            query,
            documents,
            self._embedding,
            self._reranker,
            fuse_top_k=fuse_top_k,
            document_vectors=vectors,
        )
        relevance = _normalize([score for _, score in results])

        scored = []
        for (idx, _), rel in zip(results, relevance):
            memory = candidates[idx]
            quality = memory.quality_score * EPISODE_QUALITY_WEIGHT
            success = EPISODE_SUCCESS_WEIGHT if memory.success else 0.0
            scored.append((rel * EPISODE_RELEVANCE_WEIGHT + quality + success, memory))
        scored.sort(key=lambda p: p[0], reverse=True)

        hits = [memory for _, memory in scored[:limit]]
        assert len(hits) <= limit, "query_episode_summaries must respect the limit"
        return hits

    def _episode_vector(self, memory: EpisodeMemory) -> list[float]:
        """取这条摘要的向量，缓存里没有就现算并缓存。

        向量是**派生索引**，md 才是真相：跨 run 重启后
        `FileEpisodeMemoryStore._load_all` 从磁盘重建摘要列表（含历史所有
        run 落盘的），但 `_episode_memory_vectors` 是进程内缓存、只在本 run
        写入过——历史摘要的向量缺失是常态。这里惰性补算，避免
        `KeyError`（曾让整局在第一次检索历史摘要时报错）。
        """
        vec = self._episode_memory_vectors.get(memory.episode_id)
        if vec is None:
            vec = self._embedding.embed([memory.render()])[0]
            self._episode_memory_vectors[memory.episode_id] = vec
        return vec

    @property
    def episode_summary_count(self) -> int:
        """库里有多少条跨局摘要记忆。"""
        return self._episodes.episode_summary_count()

    @require_permission("write:memory:episode")
    def store_episode_summary(self, memory: EpisodeMemory) -> EpisodeMemory:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `Brain.verify_and_summarize()` 那次合并调用里完成
        （resp.episode_memory，组装函数在 brain——见 ROADMAP 16）——这个方法
        只负责落盘、更新检索向量缓存，不调模型。**这是这个类上唯一的跨局摘要
        写入口**：只保留"先校验、再只用可信记录蒸馏"这一条路径，没有独立
        判定器就直接全量蒸馏的兜底写法不存在。

        前置条件：`memory.episode_id` 非空。
        后置条件：返回原对象（落盘后检索向量缓存同步更新）。
        """
        assert memory.episode_id, "store_episode_summary() needs a non-empty episode_id"
        self._episodes.store_episode_summary(memory)
        self._episode_memory_vectors[memory.episode_id] = self._embedding.embed([memory.render()])[
            0
        ]
        return memory

    # ---- 语义记忆：object（交互事件流的透传，判定在 harness） ----

    @require_permission("read:memory:objects")
    def query_object_events(
        self, map_id: int, before_step: int | None = None
    ) -> list[ObjectFactEvent]:
        """取这张地图上的全部交互事件，按 step 升序，直接返回不做折叠。"""
        return self._objects.query_map(map_id, before_step)

    @require_permission("read:memory:objects")
    def query_object_events_at(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """取这一格的全部交互事件（判定层的 kind 兜底查询用）。"""
        return self._objects.query(place)

    @require_permission("read:memory:objects")
    def query(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """`SemanticObjectReader` 端口的同名方法——harness 判定层
        （`object_interactions` 的 kind 兜底）把 MemoryToolPort 直接当 reader
        用，端口语义就是 `query(place)`；与 `query_object_events_at` 同一实现，
        两个名字都在是为了两个端口各自读起来自洽。"""
        return self._objects.query(place)

    @require_permission("write:memory:objects")
    def append_object_events(self, events: Sequence[ObjectFactEvent]) -> None:
        """追加一批交互事件（harness 判定层构造好；写穿，见 EventObjectStore.append）。"""
        self._objects.append(list(events))

    # ---- checkpoint 恢复：范围查询与截断（PLAN_checkpoint §6/§7） ----

    def query_step_range(
        self, episode_id: str, step_min: int, step_max: int
    ) -> list[StepMemory]:
        """取一局 `[step_min, step_max]` 区间的单步记忆（checkpoint 归档取废弃段）。"""
        return self._episodes.query_episode_range(episode_id, step_min, step_max)

    def query_object_range(
        self, episode_id: str, step_min: int, step_max: int
    ) -> list[ObjectFactEvent]:
        """取一局 `[step_min, step_max]` 区间的交互事件（checkpoint 归档取废弃段）。"""
        return self._objects.query_range(episode_id, step_min, step_max)

    def void_memory_after(self, episode_id: str, step: int) -> dict[str, int]:
        """把一局 step 之后的单步记忆与 object 事件全部截断（checkpoint 恢复）。

        返回各类被截掉的条数（归档审计用）。整局废弃时传 `step=-1`。
        """
        step_removed = len(self._episodes.query_episode_steps(episode_id)) - len(
            self._episodes.query_episode_range(episode_id, 0, step)
        )
        object_removed = len(self._objects.query_range(episode_id, 0, 10**9)) - len(
            self._objects.query_range(episode_id, 0, step)
        )
        self._episodes.truncate(episode_id, step)
        self._objects.truncate(episode_id, step)
        return {"step_memories": step_removed, "object_events": object_removed}

    # ---- 语义记忆：知识库（和坐标无关的通用先验，混合检索） ----

    @require_permission("read:memory:knowledge")
    def query_knowledge(self, req: FromHarnessToMemoryToolQueryKnowledgeReq) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从通用游戏先验里检索出这一步用得上的那几条。"""
        query, limit = req.query, req.limit
        assert query, "query_knowledge() needs a non-empty query"
        assert limit > 0, f"limit must be > 0, got {limit}"
        self._refresh_knowledge_index()
        if not self._knowledge_chunks:
            return FromHarnessToMemoryToolQueryKnowledgeResp(contents=[], sources=[])

        fuse_top_k = max(limit * 3, KNOWLEDGE_FUSE_TOP_K)
        results = hybrid_retrieve(
            query,
            self._knowledge_chunks,
            self._embedding,
            self._reranker,
            fuse_top_k=fuse_top_k,
            document_vectors=self._knowledge_vectors,
        )
        hits = results[:limit]
        return FromHarnessToMemoryToolQueryKnowledgeResp(
            contents=[self._knowledge_chunks[idx] for idx, _ in hits],
            sources=[self._knowledge_names[idx] for idx, _ in hits],
        )

    def _refresh_knowledge_index(self) -> None:
        """知识库文件的 mtime 变了才重新分片、重新 embed——**不是每次查询都重算**。

        `KnowledgeStore.chunks()` 本身很便宜（一次读盘所有文件），贵的是 `embed()`；
        用 mtime 判断"文件是不是被运营编辑过"，既保留"编辑 `.md` 文件
        不用重启进程就生效"的性质（见 `memory/semantic/semantic_store.py` 的
        `KnowledgeStore`），又不用每次查询都重新付一次 embedding 的成本。

        文件变了才重新分片和 embed，否则复用上次的索引。
        """
        current = self._knowledge.mtime()
        if current != self._knowledge_mtime:
            chunks = self._knowledge.chunks()
            self._knowledge_chunks = [text for _, text in chunks]
            self._knowledge_names = [name for name, _ in chunks]
            self._knowledge_vectors = (
                self._embedding.embed(self._knowledge_chunks) if self._knowledge_chunks else []
            )
            self._knowledge_mtime = current
