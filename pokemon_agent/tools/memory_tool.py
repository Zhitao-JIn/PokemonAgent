"""`MemoryToolPort` 的实现：Harness 和四类记忆之间那层壳。**不碰世界。**

四类记忆在这里汇合，但读写语义各不相同：

    单步情景记忆    这一局做过什么      等值筛（episode_id）+ step 数值收尾
    语义记忆 object  那一格上有什么东西  等值筛（map/place）+ step 数值收尾
    知识库          和坐标无关的先验    纯语义检索（BM25 + 向量 + reranker）
                    （手工先验 + run 学到的，两种来源一种形状）
    跨局摘要        一局的 step 总结    等值筛（conditions），**读口不做领域规则**

**存储全部落在统一索引层**（`memory/store.py`，一条记录一个
uuid 文件 + 每文件夹倒排索引，0910 重构）：
本类不再持有任何私有存储实现——它负责的只有两件事：

1. **组装 metadata**（ROADMAP 24 写入侧对称：harness 递进来的领域对象里
   提取过滤字段——`run_id/episode_id/step/map/place/...`——拼成字段字典，
   memory 层不理解其含义）；
2. **tool 层的领域知识**：step/区间比较（"step 只有同一局内才能比大小"）。

**跨局摘要的读口是纯等值过滤**（0914 定案）：场景通配匹配、相关性排序、
候选上限、条数截断全删——那些是消费方的判断，读口只把符合条件的记录全量交出来。

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

from pokemon_agent.memory import EmbeddingProvider, MemoryStore, RerankerProvider
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
    FromHarnessToMemoryToolStoreKnowledgeReq,
    FromHarnessToMemoryToolStoreKnowledgeResp,
)
from pokemon_agent.schemas.memory import (
    EpisodeMemory,
    KnowledgeRecord,
    ObjectFactEvent,
    StepMemory,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    @classmethod
    def build(
        cls,
        *,
        memory_root: str | Path | None = None,
        knowledge_root: str | Path | None = None,
        max_summaries: int = 50,
    ) -> MemoryTool:
        """造一个**接了本地检索 provider** 的 tool——装配点唯一的入口。

        **为什么把"造 `FastEmbedText` / `FastEmbedReranker`"收在这一处**
        （0913 深夜十二）：与 `BrainTool.build()` / `build_vision_provider()`
        同一条判据——"这条链路要接哪个实现"是接线知识，装配点
        （`build.py`）不该知道、也不该
        `from pokemon_agent.memory import FastEmbedReranker, FastEmbedText`。
        收进类方法之后 `build.py` 那一侧只剩一行 `MemoryTool.build()`，
        **协议归属（`memory/ports.py`）、实现归属（`memory/store.py`）、
        接线归属（本方法）三者对齐**，与 brain 那条链同形。

        **它是 `__init__` 的糖，不是第二套装配逻辑**：内部只有两个 provider
        的构造 + 转发给 `cls(...)`，没有任何额外判断——"谁 new 具体实现"
        仍然只有一个答案（`memory/` 包自己），不是又多了一个真源。

        **签名收裸字段而不是收 provider 实例**：那样装配点就得先
        `from pokemon_agent.memory import FastEmbed*` —— 正是本方法要消灭的
        那一行。收 `memory_root`/`knowledge_root`/`max_summaries` 这几个
        "装配知识"字段，跟 `BrainTool.build(text=…, judge=…)` 对齐。

        前置条件：`memory_root`/`knowledge_root` 是存在的目录或其父目录
            （不存在时 `MemoryStore` 构造期会 `mkdir(parents=True)` 自己建）。
        后置条件：返回的 tool 持有的四个 `MemoryStore` 用**同一对**
            provider 实例（四个 kind 共用一次模型加载，不重复初始化）。
        """
        # 导入放函数内：`memory` 包顶部拖着 `rank_bm25`，本模块被
        # `tools/__init__.py` 懒加载链带进来时不该顺带把它拉起来。
        from pokemon_agent.memory import FastEmbedReranker, FastEmbedText

        embedding_provider = FastEmbedText()
        reranker_provider = FastEmbedReranker()
        return cls(
            embedding_provider=embedding_provider,
            reranker_provider=reranker_provider,
            memory_root=memory_root,
            max_summaries=max_summaries,
            knowledge_root=knowledge_root,
        )

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

    # ---- 跨局摘要记忆：episode memory（按元数据过滤） ----

    def query_episode_summaries(
        self, req: FromHarnessToMemoryToolQueryEpisodeSummariesReq
    ) -> FromHarnessToMemoryToolQueryEpisodeSummariesResp:
        """按 `req.conditions` 等值过滤取跨局摘要——**不做任何领域规则**（0914 定案）。

        原先这一跳自带四件套：场景通配匹配（`EpisodeMemory.matches_scene`）、
        混合检索排相关性（`rank` + 质量/成败加权归一化）、候选上限、`limit` 截断，
        外加"必须传 run_id"的跨 run 禁令。**全部删除**——它们都是消费方的领域
        判断，住在读口上等于把"取哪些、取几条"从消费方手里拿走。现在这一跳只剩
        metadata 交集 + 反序列化。

        顺序：按 `episode_id` 字典序落定——**这不是相关性排序**，只是让同一个库
        读两次拿到同一个顺序（`MemoryStore.filter` 的交集走 `set`，本身无序）。
        """
        out: list[EpisodeMemory] = []
        for _record_id, _meta, payload, text in self._summaries.get_many(
            self._summaries.filter(req.conditions)
        ):
            try:
                out.append(EpisodeMemory(**payload, markdown=text))
            except ValidationError:
                continue
        out.sort(key=lambda memory: memory.episode_id)
        return FromHarnessToMemoryToolQueryEpisodeSummariesResp(summaries=out)

    def store_episode_summary(
        self, req: FromHarnessToMemoryToolStoreEpisodeSummaryReq
    ) -> FromHarnessToMemoryToolStoreEpisodeSummaryResp:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `BrainTool.summarize()` 里完成（resp.episode_memory——
        见 ROADMAP 16）——这个方法只负责落一个 md 记录文件、进索引，不调模型。
        **这是这个类上唯一的跨局摘要写入口**：只保留"先校验、再只用可信记录
        蒸馏"这一条路径，没有独立判定器就直接全量蒸馏的兜底写法不存在。

        **两种合法形态**（0914 S3）：

        - 常规——`markdown` 是蒸馏出的正文；
        - **正文全空**——"这一局压根没有可蒸馏的正文"（整局异常，或收尾时没有
          一条可信的 step 记忆）。它不是"蒸馏的降级"，而是那种局在记忆里唯一的
          痕迹；写入点是 `harness/run/nodes/review.py::_leave_chapter()`，它保证
          **每局恰好留一条**。**没有标记位**（0914 99 删了 `chapter_only`）——
          空不空看 `markdown` / `summary` 自己。

        落盘形态：`memory/episode_memory/<uuid>.md`——frontmatter 是结构化
        元数据，正文是蒸馏出的 markdown。**文件用 uuid 命名**（`filename`
        这个模型字段 0914 98 已整个删掉——它在 uuid 命名落地那天就没有读方了）。
        写完按 `max_summaries` 裁剪：超限淘汰质量最差的，
        **归档**进 `memory/voided-<ts>/episode_memory/`（淘汰是容量机制不是销毁）。

        前置条件：`req.memory.episode_id` 非空；**正文与章自洽**——正文要么整条
            完整、要么整条为空（半截的正文是写入方在伪造内容）。
        后置条件：resp.memory 是原对象。
        """
        memory = req.memory
        assert memory.episode_id, "store_episode_summary() needs a non-empty episode_id"
        assert bool(memory.markdown.strip()) == bool(memory.summary.strip()), (
            "正文要么整条完整、要么整条为空——markdown 与 summary 必须同真同假"
        )
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

    def _voided_dir(self) -> Path:
        """归档根：`memory/voided-<ts>/`——`_trim_summaries` 淘汰最差的摘要时用它。

        独立于任何恢复语义：本仓已无 checkpoint 恢复（见 `CHANGELOG.md` 本次
        条目），这个目录现在只服务"容量淘汰时留档"这一条路径。
        """
        return self._memory_root / f"voided-{time.strftime('%Y%m%d-%H%M%S')}"

    # ---- 语义记忆：object（交互事件流的透传，判定在 harness） ----

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        """取交互事件，按 step 升序，直接返回不做折叠。

        `map_id` 为 None = **不按地图筛**（0914 S2 放开）：run 级消费方（`plan`）
        没有"当前地图"，要的是本 run 涉及过的地图上的全部事实。`before_step` 是
        **区间条件**，不进索引交集（索引层不认识"大于"）——等值条件先筛小，
        再在这里数值收尾"检索不读未来"。
        """
        conditions = {"map_id": str(req.map_id)} if req.map_id is not None else {}
        events = self._object_events(conditions)
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
                    "object_kind": event.object_kind,
                    "outcome": event.outcome,
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

    # ---- 语义记忆：知识库（和坐标无关的先验 + run 期间学到的，混合检索） ----
    def query_knowledge(
        self, req: FromHarnessToMemoryToolQueryKnowledgeReq
    ) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从知识库里检索出这一步用得上的那几条。纯语义检索，无等值条件。

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

    def store_knowledge(
        self, req: FromHarnessToMemoryToolStoreKnowledgeReq
    ) -> FromHarnessToMemoryToolStoreKnowledgeResp:
        """落库一批**已经组装好**的世界知识，不调模型（0914 S4）。

        组装在 `BrainTool.extract()` 里完成（`resp.records`），本方法只做三件事：
        **判重 → 落一个 md 记录文件 → 更新检索向量缓存**。

        **落盘形态与这个家族的手工先验逐字一致**（`metadata={"source","topic"}`、
        `payload={}`、`text=record.text`）：`query_knowledge` 因此不需要区分"这条是
        人手写的还是 run 学到的"——两种来源在检索时平权，只有 metadata 里的
        `source` 值不同（文件名 vs `{run_id}/{episode_id}`）。

        **判重按 `(topic, 正文逐字)`**：同一件事被两局分别学到时不该堆第二份。
        判据刻意只认"完全一样"——相近但不完全相同是**该留下**的（措辞差异常常
        带着新信息），合并是人的判断，不是存储层的。判重前先 `refresh_changed()`
        跟读口对齐：运营刚手抄进库的同一条也要认得出来。

        前置条件：`req.records` 里每条都通过了 `KnowledgeRecord` 自己的字段校验
            （`topic`/`content`/`source` 非空由模型约束保证，这里不重复断言）。
        后置条件：`stored` 是 `req.records` 的子序列、顺序一致；空输入返回空
            `stored` 且一个文件都不写——那一跳什么都不做是合法结果。
        """
        if not req.records:
            return FromHarnessToMemoryToolStoreKnowledgeResp()

        self._knowledge.refresh_changed()
        stored: list[KnowledgeRecord] = []
        for record in req.records:
            known = {
                text
                for _record_id, _meta, _payload, text in self._knowledge.get_many(
                    self._knowledge.filter({"topic": record.topic})
                )
            }
            if record.text in known:
                continue
            self._knowledge.put(
                metadata={"source": record.source, "topic": record.topic},
                payload={},
                text=record.text,
            )
            stored.append(record)
        return FromHarnessToMemoryToolStoreKnowledgeResp(stored=stored)

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
