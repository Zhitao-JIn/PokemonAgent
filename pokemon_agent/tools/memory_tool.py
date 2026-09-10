"""`MemoryToolPort` 的实现：Harness 和四类记忆之间那层壳。**不碰世界。**

四类记忆在这里汇合，但读写语义各不相同：

    单步情景记忆    这一局做过什么      等值筛（episode_id）+ step 数值收尾
    语义记忆 object  那一格上有什么东西  等值筛（map/place）+ step 数值收尾
    知识库          和坐标无关的先验    纯语义检索（BM25 + 向量 + reranker）
    跨局摘要        别的局蒸馏的经验    run_id 等值 + 场景通配匹配 + 混合检索

**存储全部落在统一索引层**（`memory/store.py`，一条记录一个
uuid 文件 + 每文件夹倒排索引，0910 重构，见 `PLAN_memory_trace_layout.md`）：
本类不再持有任何私有存储实现——它负责的只有两件事：

1. **组装 metadata**（ROADMAP 24 写入侧对称：harness 递进来的领域对象里
   提取过滤字段——`run_id/episode_id/step/map/place/...`——拼成字段字典，
   memory 层不理解其含义）；
2. **tool 层的领域知识**：step/区间比较（"step 只有同一局内才能比大小"）、
   场景通配匹配（`EpisodeMemory.matches_scene`）、摘要的质量/成功加权混排。

**混合检索的两路分数要先各自归一化再加权**：BM25 的分无上界，向量余弦在 [-1,1]，
直接相加等于让 BM25 独裁。

**"让记录消失"只有一个语义、也只有一个时机——归档**（0910 拍板）：
checkpoint 恢复时把游标之后不再成立的那批 step 记忆与 object 事件搬进
`voided-<ts>/`（不 unlink，留档可查）。**局正常收尾什么都不做**——step 记忆
按 `episode_id` 查询天然隔离，没有查询方会跨局取到它，不需要清场。所以既没有
"摘索引但文件原地留"的中间态（它在索引重建时无法还原，会让丢弃的记录复活），
也没有"例行清理"这第二个归档动机。
"""

from __future__ import annotations

import time
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from pokemon_agent.interfaces import EmbeddingProvider, RerankerProvider
from pokemon_agent.memory import MemoryStore
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
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, StepMemory
from pokemon_agent.schemas.world import PlaceInWorld

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 跨局摘要记忆排序：混合检索（关键词 BM25 + 向量 + reranker 精排，见
# `memory/retrieval.py`）给出的 reranker 分数是"文本相关性"这一项，值域没有
# 自然的上下界（cross-encoder 输出的是未经归一化的 logits），所以每次查询后
# 现算 min-max 归一化到 [0, 1] 再叠加权重——不能直接拿 reranker 的原始分数
# 和质量分/成败这些本来就在 [0, 1] 或布尔量级的信号相加，量纲对不上。
# 权重比例：相关性最重要（"这条经验到底切不切题"），
# 质量/成功用来在相关性接近时挑更可信的那条，不该反过来压过相关性。
EPISODE_RELEVANCE_WEIGHT = 10.0
EPISODE_QUALITY_WEIGHT = 3.0
EPISODE_SUCCESS_WEIGHT = 1.5

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


def _step_within(step: int, keep_step: int) -> bool:
    """一条记录是否落在 void 的保留区间内（`step <= keep_step`；-1 = 整局废弃）。"""
    return step <= keep_step


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有四个统一索引层实例（四类记忆各一个
    文件夹），不持有任何记录状态——记录在盘上，索引在各自文件夹里。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
        memory_root: str | Path | None = None,
        max_summaries: int = 50,
        knowledge_root: str | Path | None = None,
    ) -> None:
        """接好检索用的两个模型 provider 与 `memory/` 根目录（缺省仓库根级）。

        测试换隔离目录只动 `memory_root`；存储形状（一条一文件 + index.json）
        对所有调用方一致，不再需要为每类记忆注入各自的 mock store。

        知识库是全局共享的先验、不随 run/测试隔离（0908 拍板⑩）——
        `knowledge_root` 只在确要另指知识库位置时才传，缺省始终落在
        仓库根级 `memory/knowledge_memory/`，与 `memory_root` 无关。
        """
        root = Path(memory_root) if memory_root is not None else _PROJECT_ROOT / "memory"
        self._memory_root = root
        self._steps = MemoryStore(embedding_provider, reranker_provider, "step_memory", root)
        self._objects = MemoryStore(embedding_provider, reranker_provider, "object_memory", root)
        self._summaries = MemoryStore(embedding_provider, reranker_provider, "episode_memory", root)
        knowledge_dir = (
            Path(knowledge_root) if knowledge_root is not None else _PROJECT_ROOT / "memory"
        )
        self._knowledge = MemoryStore(
            embedding_provider, reranker_provider, "knowledge_memory", knowledge_dir
        )
        self._max_summaries = max_summaries
        """跨局摘要的上限：超过就按质量淘汰最差的（平手淘汰最旧），归档不删。
        防止经验库无限膨胀——检索候选越多越慢、越杂。"""
        self._step_max: dict[str, int] = {}
        """`episode_id → 该局 step 记忆的最大 step`（append 单调前置的依据）。
        进程内缓存，首次写某局时从索引现查填满——比旧实现"启动全量读回"便宜。"""
        self._object_max: dict[str, int] = {}
        """同上，object 事件专用。"""

    # ---- 情景记忆：episodic（单步，全量，不检索） ----

    def query_episode_steps(
        self, req: FromHarnessToMemoryToolQueryEpisodeStepsReq
    ) -> FromHarnessToMemoryToolQueryEpisodeStepsResp:
        """取这一局全部的单步情景记忆，按 step 升序。"""
        entries = self._episode_steps(req.episode_id)
        return FromHarnessToMemoryToolQueryEpisodeStepsResp(steps=entries)

    def query_recent_steps(
        self, req: FromHarnessToMemoryToolQueryRecentStepsReq
    ) -> FromHarnessToMemoryToolQueryRecentStepsResp:
        """取这一局最近几条情景记忆（已按 step 升序，取尾部）。"""
        assert req.limit > 0, f"limit must be > 0, got {req.limit}"
        entries = self._episode_steps(req.episode_id)[-req.limit :]
        return FromHarnessToMemoryToolQueryRecentStepsResp(steps=entries)

    def store_episode_step(self, req: FromHarnessToMemoryToolStoreEpisodeStepReq) -> None:
        """写入一条情景记忆：tool 层组装 metadata → 索引层落一个 uuid 文件。

        前置条件：`req.entry.rationale` 非空；`entry.step` ≥ 该局已有最大 step
        （恢复后同局重跑，void 归档把缓存退回保留区间，重跑的 step 号自然过闸）。
        """
        entry = req.entry
        assert entry.rationale, "store_episode_step() got an entry without a rationale"
        self._check_step_monotonic(entry.episode_id, entry.step, self._step_max, "step_memory")
        map_id = entry.before.place.map_id if entry.before.place is not None else ""
        self._steps.put(
            metadata={
                "run_id": entry.run_id,
                "episode_id": entry.episode_id,
                "step": str(entry.step),
                "map_id": str(map_id),
            },
            payload=entry.model_dump(),
            text="",
        )
        self._step_max[entry.episode_id] = max(self._step_max.get(entry.episode_id, 0), entry.step)

    def _episode_steps(self, episode_id: str) -> list[StepMemory]:
        """等值筛（episode_id）→ 解析 payload → 按 step 数值升序。"""
        assert episode_id, "episode step query needs a non-empty episode_id"
        entries: list[StepMemory] = []
        for _uuid, _meta, payload, _text in self._steps.get_many(
            self._steps.filter({"episode_id": episode_id})
        ):
            try:
                entries.append(StepMemory.model_validate(payload))
            except ValidationError:
                continue
        return sorted(entries, key=lambda m: m.step)

    # ---- 跨局摘要记忆：episode memory（混合检索） ----

    def query_episode_summaries(
        self, req: FromHarnessToMemoryToolQueryEpisodeSummariesReq
    ) -> FromHarnessToMemoryToolQueryEpisodeSummariesResp:
        """run_id 等值筛（索引层）→ 场景通配匹配（领域规则，`matches_scene`）→
        质量粗筛（候选上限）→ 混合检索排出"文本相关性"（`rank`）→ 叠加质量分
        和是否成功两个信号，取前 `limit` 条。

        `run_id` 非空时只检索该 run 沉淀的摘要——禁止跨 run 检索，失败局
        蒸馏出的"已验证"经验一旦被当真就污染决策（取舍见 `CHANGELOG.md`
        2026-09-03 条目；`episode_harness` 传 `self._run_id`）。
        """
        scene, query, limit, run_id = req.scene, req.query, req.limit, req.run_id
        assert scene, "query_episode_summaries() needs a non-empty scene"
        assert limit > 0, f"limit must be > 0, got {limit}"

        conditions = {"run_id": run_id} if run_id else {}
        candidates: list[tuple[str, EpisodeMemory]] = []
        for record_id, _meta, payload, text in self._summaries.get_many(
            self._summaries.filter(conditions)
        ):
            try:
                memory = EpisodeMemory(**payload, markdown=text)
            except ValidationError:
                continue
            if memory.matches_scene(scene):
                candidates.append((record_id, memory))
        if not candidates:
            return FromHarnessToMemoryToolQueryEpisodeSummariesResp(summaries=[])

        # 候选上限：超过就按质量分粗筛（经验库的价值是高质量可复用经验，
        # 质量最低的先出局——精排本来也会把低质量排后面，粗筛只是省掉白做）。
        if len(candidates) > EPISODE_CANDIDATE_CAP:
            candidates.sort(key=lambda im: im[1].quality_score, reverse=True)
            candidates = candidates[:EPISODE_CANDIDATE_CAP]

        fuse_top_k = max(limit * 3, EPISODE_FUSE_TOP_K)
        results = self._summaries.rank([u for u, _ in candidates], query, fuse_top_k)
        relevance = _normalize([score for _, score in results])
        by_uuid = dict(candidates)

        scored = []
        for (record_id, _), rel in zip(results, relevance, strict=True):
            memory = by_uuid[record_id]
            quality = memory.quality_score * EPISODE_QUALITY_WEIGHT
            success = EPISODE_SUCCESS_WEIGHT if memory.success else 0.0
            scored.append((rel * EPISODE_RELEVANCE_WEIGHT + quality + success, memory))
        scored.sort(key=lambda p: p[0], reverse=True)

        hits = [memory for _, memory in scored[:limit]]
        assert len(hits) <= limit, "query_episode_summaries must respect the limit"
        return FromHarnessToMemoryToolQueryEpisodeSummariesResp(summaries=hits)

    def store_episode_summary(
        self, req: FromHarnessToMemoryToolStoreEpisodeSummaryReq
    ) -> FromHarnessToMemoryToolStoreEpisodeSummaryResp:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `Brain.verify_and_summarize()` 那次合并调用里完成
        （resp.episode_memory，组装函数在 brain——见 ROADMAP 16）——这个方法
        只负责落一个 md 记录文件、进索引，不调模型。**这是这个类上唯一的跨局
        摘要写入口**：只保留"先校验、再只用可信记录蒸馏"这一条路径，没有独立
        判定器就直接全量蒸馏的兜底写法不存在。

        落盘形态：`memory/episode_memory/<uuid>.md`——frontmatter 是结构化
        元数据，正文是蒸馏出的 markdown（LLM 给的 `filename` 字段退役，
        uuid 文件名天然不撞）。写完按 `max_summaries` 裁剪：超限淘汰质量最差的，
        **归档**进 `memory/voided-<ts>/episode_memory/`（淘汰是容量机制不是销毁）。

        前置条件：`req.memory.episode_id` 非空。
        后置条件：resp.memory 是原对象。
        """
        memory = req.memory
        assert memory.episode_id, "store_episode_summary() needs a non-empty episode_id"
        assert memory.markdown.strip(), "store_episode_summary() got an empty markdown"
        self._summaries.put(
            metadata={
                "run_id": memory.run_id,
                "episode_id": memory.episode_id,
                "success": str(memory.success),
                "quality_score": f"{memory.quality_score:.2f}",
                "scene": "|".join(memory.applicable_scenes),
            },
            payload=memory.model_dump(exclude={"markdown"}),
            text=memory.markdown,
        )
        self._trim_summaries()
        return FromHarnessToMemoryToolStoreEpisodeSummaryResp(memory=memory)

    def _trim_summaries(self) -> None:
        """超过 `max_summaries` 时淘汰质量最差的（平手淘汰先入库的）。

        按**质量**淘汰而不是 FIFO——FIFO 会保留一堆早期低质量经验；质量最低的
        先走。淘汰 = 归档（搬进 voided），不删除。"""
        if self._summaries.count() <= self._max_summaries:
            return
        pool: list[tuple[str, float]] = []
        for record_id, _meta, payload, _text in self._summaries.get_many(
            self._summaries.filter({})
        ):
            try:
                pool.append((record_id, EpisodeMemory(**payload).quality_score))
            except ValidationError:
                continue
        if not pool:
            return
        worst = min(pool, key=lambda uq: uq[1])[0]
        self._summaries.archive_many([worst], self._voided_dir() / "episode_memory")

    # ---- 语义记忆：object（交互事件流的透传，判定在 harness） ----

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        """取这张地图上的全部交互事件，按 step 升序，直接返回不做折叠。

        `before_step` 是**区间条件**，不进索引交集（索引层不认识"大于"）：
        先按 map_id 等值筛小，再在这里数值收尾——"检索不读未来"。
        """
        events = self._object_events({"map_id": str(req.map_id)})
        if req.before_step is not None:
            events = [e for e in events if e.step < req.before_step]
        return FromHarnessToMemoryToolQueryObjectEventsResp(events=events)

    def query_object_events_at(
        self, req: FromHarnessToMemoryToolQueryObjectEventsAtReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsAtResp:
        """取这一格的全部交互事件（判定层的 kind 兜底查询用）。"""
        place = req.place
        events = self._object_events({"map_id": str(place.map_id), "place": place.key})
        return FromHarnessToMemoryToolQueryObjectEventsAtResp(events=events)

    def query(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """`SemanticObjectReader` 端口的同名方法——harness 判定层
        （`object_interactions` 的 kind 兜底）把 MemoryToolPort 直接当 reader
        用，端口语义就是 `query(place)`；与 `query_object_events_at` 同一实现，
        两个名字都在是为了两个端口各自读起来自洽。"""
        return self._object_events({"map_id": str(place.map_id), "place": place.key})

    def append_object_events(self, req: FromHarnessToMemoryToolAppendObjectEventsReq) -> None:
        """追加一批交互事件（harness 判定层构造好；逐条落一个 uuid 文件，写穿）。

        前置条件：每个事件的 step ≥ 其所在局已有最大 step（等于容忍崩溃窗口的
        重复，恢复时的 void 归档负责清理）。
        """
        for event in req.events:
            self._check_step_monotonic(
                event.episode_id, event.step, self._object_max, "object_memory"
            )
            self._objects.put(
                metadata={
                    "run_id": event.run_id,
                    "episode_id": event.episode_id,
                    "step": str(event.step),
                    "map_id": str(event.place.map_id),
                    "place": event.place.key,
                    "kind": event.kind,
                    "type": event.type,
                },
                payload=event.model_dump(),
                text="",
            )
            self._object_max[event.episode_id] = max(
                self._object_max.get(event.episode_id, 0), event.step
            )

    def _object_events(self, conditions: dict[str, str]) -> list[ObjectFactEvent]:
        """等值筛（索引层交集）→ 解析 discriminated union → 按 step 数值升序。"""
        adapter = TypeAdapter(ObjectFactEvent)
        events: list[ObjectFactEvent] = []
        for _uuid, _meta, payload, _text in self._objects.get_many(
            self._objects.filter(conditions)
        ):
            try:
                events.append(adapter.validate_python(payload))
            except ValidationError:
                continue
        return sorted(events, key=lambda e: e.step)

    # ---- checkpoint 恢复：废弃记忆归档（PLAN_memory_trace_layout §7 步骤 3） ----

    def void_memory_after(
        self, req: FromHarnessToMemoryToolVoidMemoryAfterReq
    ) -> FromHarnessToMemoryToolVoidMemoryAfterResp:
        """把一局 `req.step` 之后不再成立的记忆**归档**（checkpoint 恢复）。

        圈定集合是 tool 层的职责：等值筛（`episode_id`，索引层）+ 数值收尾
        （`step > keep_step`，领域知识——索引不理解"大于"），再交给 store 搬走。
        搬进 `memory/voided-<ts>/<kind>/`，不 unlink：被 resume 废弃的分支也留档可查。
        归档即摘索引，所以盘上索引始终对得上账、不需要额外重建。

        三类进作废范围，筛法各不相同：

        - `step_memory` / `object_memory`：`episode_id` 等值 + `step > keep_step`。
        - `episode_memory`：只按 `episode_id`，**不做 step 筛**——局摘要由局收尾
          （verify → `write_episode`）蒸馏产生，而局收尾发生在本局最后一个
          checkpoint **之后**，所以只要在做本局的恢复（`keep_step` 恒 ≤ 末步），
          这份摘要描述的就是"废弃时间线跑出来的那一局结果"，必须跟着归档。
          漏掉它，重跑会落下第二条同 `episode_id` 的摘要，而 `query_episode_summaries`
          按 `run_id` 等值筛时两条都进候选（0909 曾以"废弃窗口内没有新摘要"为由
          排除本类，0910 真机恢复实测 4/4 复现该前提不成立）。
        - `knowledge` 不进：全局先验、不属任何一局，没有 `episode_id`。

        返回各类被归档的条数。整局废弃时传 `req.step=-1`。
        """
        episode_id, keep_step = req.episode_id, req.step
        # 归档目录一次算好：三类记录必须落在**同一个** voided-<ts>/ 里，逐类调
        # `_voided_dir()` 会在跨秒时切成两个目录（读端按目录 diff 判断"本次归档了
        # 什么"的脚本会因此漏看）。
        voided_dir = self._voided_dir()
        step_memories_voided = self._void_kind(
            self._steps, episode_id, keep_step, self._step_max, voided_dir
        )
        object_events_voided = self._void_kind(
            self._objects, episode_id, keep_step, self._object_max, voided_dir
        )
        episode_memories_voided = self._void_episode_summaries(episode_id, voided_dir)
        return FromHarnessToMemoryToolVoidMemoryAfterResp(
            removed={
                "step_memories": step_memories_voided,
                "object_events": object_events_voided,
                "episode_memories": episode_memories_voided,
            }
        )

    def _void_kind(
        self,
        store: MemoryStore,
        episode_id: str,
        keep_step: int,
        max_cache: dict[str, int],
        voided_dir: Path,
    ) -> int:
        """等值筛（episode_id）→ 数值筛（step > keep_step）→ 归档。

        前置条件由调用方保证：episode_id 是目标局或废弃局，voided_dir 是同一次
        `void_memory_after` 算好的归档根。归档后把该局的 max 缓存退回保留区间的
        最大 step——恢复后同局重跑的 step 号自然过闸。
        """
        doomed: list[str] = []
        survivors_max = 0
        for record_id, _meta, payload, _text in store.get_many(
            store.filter({"episode_id": episode_id})
        ):
            step = int(payload.get("step", 0))
            if _step_within(step, keep_step):
                survivors_max = max(survivors_max, step)
            else:
                doomed.append(record_id)
        moved = store.archive_many(doomed, voided_dir / store.kind)
        max_cache[episode_id] = survivors_max
        return moved

    def _void_episode_summaries(self, episode_id: str, voided_dir: Path) -> int:
        """归档该局的跨局摘要——**整条搬走，不做 step 筛**（摘要没有 step 概念）。

        局摘要在局的收尾蒸馏，而收尾永远晚于该局最后一个 checkpoint：恢复任意
        一步都意味着废弃分支里那次收尾作废，它写下的摘要必须跟着走。不搬的话
        重跑会落下第二条同 `episode_id` 的记录，同一局在检索口就有了两份互相
        矛盾的账。这里不过 `_void_kind`，因为没有 step 可筛、也没有 max 缓存
        要维护（摘要不参与 step 单调性前置）。
        """
        doomed = self._summaries.filter({"episode_id": episode_id})
        return self._summaries.archive_many(doomed, voided_dir / self._summaries.kind)

    def _voided_dir(self) -> Path:
        """废弃归档根：`memory/voided-<ts>/`（每次 void 一个新目录，先归档后继续）。"""
        return self._memory_root / f"voided-{time.strftime('%Y%m%d-%H%M%S')}"

    # ---- 语义记忆：知识库（和坐标无关的通用先验，混合检索） ----

    def query_knowledge(
        self, req: FromHarnessToMemoryToolQueryKnowledgeReq
    ) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从通用游戏先验里检索出这一步用得上的那几条。纯语义检索，无等值条件。

        查前先做一次 mtime 增量刷新——运营直接编辑 `memory/knowledge_memory/*.md`
        不用重启进程就生效（原 KnowledgeStore 的性质，等价物见 index 层
        `refresh_changed`）。
        """
        query, limit = req.query, req.limit
        assert query, "query_knowledge() needs a non-empty query"
        assert limit > 0, f"limit must be > 0, got {limit}"
        self._knowledge.refresh_changed()
        hits = self._knowledge.search(query, limit)
        contents: list[str] = []
        sources: list[str] = []
        for record_id in hits:
            got = self._knowledge.get(record_id)
            if got is None:
                continue
            metadata, _payload, text = got
            contents.append(text)
            sources.append(metadata.get("source", ""))
        return FromHarnessToMemoryToolQueryKnowledgeResp(contents=contents, sources=sources)

    # ---- 内部 ----

    def _check_step_monotonic(
        self, episode_id: str, step: int, max_cache: dict[str, int], kind: str
    ) -> None:
        """append 单调前置：step ≥ 该局已有最大 step。缓存 miss 时从索引现查
        填满（只发生在一局的第一笔写入前），之后 O(1)。"""
        if episode_id not in max_cache:
            store = self._steps if kind == "step_memory" else self._objects
            existing = [
                int(payload.get("step", 0))
                for _u, _m, payload, _t in store.get_many(store.filter({"episode_id": episode_id}))
            ]
            max_cache[episode_id] = max(existing, default=0)
        assert step >= max_cache[episode_id], (
            f"store got a stale entry: episode {episode_id} "
            f"step {step} < max {max_cache[episode_id]}"
        )
