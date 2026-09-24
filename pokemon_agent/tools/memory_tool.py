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

**容量淘汰**（0910 起，0916 改法）：跨局摘要超 `max_summaries` 时按质量淘汰最差的
一条——**直接删**（`LocalMemoryStore.delete_many`）。0916 之前是"搬进
`voided-<ts>/<kind>/` 留档"，那套归档已删：要留档就在淘汰之前拍一张快照
（`snapshot()` 打整个根成 zip、`restore()` 以 zip 为准还原回来）。

**局正常收尾什么都不做**——step 记忆按 `episode_id` 查询天然隔离，没有查询方会
跨局取到它，不需要清场。

**快照由 memory 自己管**（0916）：`snapshot(name)` 把整个记忆根打成
`memory/snapshots/<name>.zip` 并返回路径；`restore(archive)` 用一个 zip 覆盖回来。
harness 只给 zip 的名字——"快照放哪、怎么打包"不是它该知道的事。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from pokemon_agent.memory import EmbeddingProviderPort, LocalMemoryStore, RerankerProviderPort
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolAppendObjectEventsReq,
    FromHarnessToMemoryToolQueryActMemoriesReq,
    FromHarnessToMemoryToolQueryActMemoriesResp,
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryEpisodeSummariesResp,
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryKnowledgeResp,
    FromHarnessToMemoryToolQueryObjectEventsAtReq,
    FromHarnessToMemoryToolQueryObjectEventsAtResp,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToMemoryToolQueryObjectEventsResp,
    FromHarnessToMemoryToolQueryRecentActMemoriesReq,
    FromHarnessToMemoryToolQueryRecentActMemoriesResp,
    FromHarnessToMemoryToolQueryTaskMemoriesReq,
    FromHarnessToMemoryToolQueryTaskMemoriesResp,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolRestoreMemoryResp,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryResp,
    FromHarnessToMemoryToolStoreActMemoryReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryResp,
    FromHarnessToMemoryToolStoreKnowledgeReq,
    FromHarnessToMemoryToolStoreKnowledgeResp,
    FromHarnessToMemoryToolStoreTaskMemoryReq,
)
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    KnowledgeRecord,
    ObjectFactEvent,
    TaskMemory,
)


def _default_root() -> Path:
    """缺省落盘根：**进程启动目录**下的 `memory/`（0916 起）。

    与 `memory/store.py` 同一条规矩。四族记忆**一视同仁**地住在它下面各自的
    `<kind>/` 子文件夹里——"哪一族住哪"不是一个需要逐个指定的问题。
    """
    return Path.cwd() / "memory"


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有四个统一索引层实例（四类记忆各一个
    子文件夹），不持有任何记录状态——记录在盘上，索引在各自文件夹里。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProviderPort,
        reranker_provider: RerankerProviderPort,
        memory_root: str | Path | None = None,
        max_summaries: int = 50,
    ) -> None:
        """接好检索用的两个模型 provider，以及**整个记忆库的落盘根**。

        `memory_root` 是**父目录**（`LocalMemoryStore` 会在它下面建 `<kind>/`），
        缺省为**进程启动目录**下的 `memory/`（0916 起，不再写死仓库根）。
        四族一视同仁——只指定这一个位置，四族各占一个子文件夹。测试换隔离
        目录就传 `tmp_path`。

        **0916 的两次口径变更**：① 落盘根从"代码住在哪"改成"启动时指定"；
        ② 一度改成"四族各一个 root"（`step_root` / `object_root` / `episode_root`
        / `knowledge_root`），同日回退——四族没有哪一族是特殊的，为它们各开
        一个开关只是把"一个位置"说成四遍。现在只是一个 `memory_root`。
        """
        self._root = Path(memory_root) if memory_root is not None else _default_root()
        self._steps = self._store(embedding_provider, reranker_provider, "step_memory")
        self._objects = self._store(embedding_provider, reranker_provider, "object_memory")
        self._summaries = self._store(embedding_provider, reranker_provider, "episode_memory")
        self._tasks = self._store(embedding_provider, reranker_provider, "task_memory")
        self._knowledge = self._store(embedding_provider, reranker_provider, "knowledge_memory")
        self._max_summaries = max_summaries
        """跨局摘要的上限：超过就按质量淘汰最差的（平手淘汰最旧），**删掉**。
        防止经验库无限膨胀——检索候选越多越慢、越杂。"""
        self._step_max: dict[str, int] = {}
        """`episode_id → 该局 step 记忆的最大 step`（append 单调前置的依据）。
        进程内缓存，首次写某局时从索引现查填满——比旧实现"启动全量读回"便宜。"""
        self._object_max: dict[str, int] = {}
        """同上，object 事件专用。"""

    def _store(
        self,
        embedding_provider: EmbeddingProviderPort,
        reranker_provider: RerankerProviderPort,
        kind: str,
    ) -> LocalMemoryStore:
        """按 kind 造一个绑在**同一个根**下面的 `LocalMemoryStore`（各占 `<kind>/`）。"""
        return LocalMemoryStore(embedding_provider, reranker_provider, kind, self._root)

    def _sync_max_caches(self) -> None:
        """清掉 append 单调缓存——恢复（覆盖）之后盘上换了内容，这两个缓存不
        再可信。不清的后果是"恢复回来的那一局，step 号被旧缓存挡住"（写不进去），
        而它只会在下一次 `store_act_memory` 的 assert 上炸，很难回溯到这里。
        """
        self._step_max.clear()
        self._object_max.clear()

    @classmethod
    def build(
        cls,
        *,
        memory_root: str | Path | None = None,
        max_summaries: int = 50,
    ) -> MemoryTool:
        """造一个**接了本地检索 provider** 的 tool——装配点唯一的入口。

        **为什么把"造 `LocalEmbeddingProvider` / `LocalRerankerProvider`"收在这一处**
        （0913 深夜十二）：与 `BrainTool.build()` / `build_vision_provider()`
        同一条判据——"这条链路要接哪个实现"是接线知识，装配点
        （`build.py`）不该知道、也不该
        `from pokemon_agent.memory import LocalRerankerProvider, LocalEmbeddingProvider`。
        收进类方法之后 `build.py` 那一侧只剩一行 `MemoryTool.build()`，
        **协议归属（`memory/ports.py`）、实现归属（`memory/store.py`）、
        接线归属（本方法）三者对齐**，与 brain 那条链同形。

        **它是 `__init__` 的糖，不是第二套装配逻辑**：内部只有两个 provider
        的构造 + 转发给 `cls(...)`，没有任何额外判断——"谁 new 具体实现"
        仍然只有一个答案（`memory/` 包自己），不是又多了一个真源。

        **签名收裸字段而不是收 provider 实例**：那样装配点就得先
        `from pokemon_agent.memory import FastEmbed*` ——正是本方法要消灭的
        那一行。收 `memory_root` + `max_summaries` 这两个"装配知识"字段，
        跟 `BrainTool.build(text=…, judge=…)` 对齐。

        前置条件：`memory_root` 是存在的目录或其父目录
            （不存在时 `LocalMemoryStore` 构造期会 `mkdir(parents=True)` 自己建）。
        后置条件：返回的 tool 持有的四个 `LocalMemoryStore` 用**同一对**
            provider 实例（四个 kind 共用一次模型加载，不重复初始化）。
        """
        # 导入放函数内：`memory` 包顶部拖着 `rank_bm25`，本模块被
        # `tools/__init__.py` 懒加载链带进来时不该顺带把它拉起来。
        from pokemon_agent.memory import LocalEmbeddingProvider, LocalRerankerProvider

        embedding_provider = LocalEmbeddingProvider()
        reranker_provider = LocalRerankerProvider()
        return cls(
            embedding_provider=embedding_provider,
            reranker_provider=reranker_provider,
            memory_root=memory_root,
            max_summaries=max_summaries,
        )

    # ---- 快照 / 恢复（0916：zip 由 memory 自己管，harness 只给名字） ----

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        """把整个记忆库打成一个 zip，返回它的路径。

        **走 `step_memory` 那个实例去拍**：快照打的是整个根（四族的记录文件 +
        各自的 `index.json`），不是某一个 kind——所以四个实例里任一个拿到的结果
        都一样（`LocalMemoryStore.snapshot` 的 docstring 有说明）。这里挑第一个纯粹是
        为了有个确定的入口。

        zip 落在 `<memory_root>/snapshots/<req.name>.zip`，同名覆盖。**路径由
        memory 层决定**（`SNAPSHOTS_DIRNAME`），harness 只给名字。

        前置条件：`req.name` 非空、不含路径分隔符。
        后置条件：返回的 `archive` 是盘上存在的 zip。
        """
        archive = self._steps.snapshot(req.name)
        return FromHarnessToMemoryToolSnapshotMemoryResp(archive=str(archive))

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        """用一个 zip 把记忆库**还原到那一刻**——以 zip 为准。

        **库里多出来的会被删掉**：zip 里有的记录文件按 zip 写（同名直接盖），
        zip 里没有的记录文件从库里消失。语义单位是**整个库**，不是"往库上叠一层"
        ——后者做不到"恢复到某个存档"（越恢复越多）。

        四个 store 的内存态随后各重读一次（对账通过就直接用
        zip 里的 `index.json`），append 单调缓存也清掉——恢复回来的局应该能
        接着写。

        前置条件：`req.archive` 是存在的 zip。
        后置条件：resp.unpacked 是解出的文件数；四族索引与盘上一致。
        """
        unpacked = self._steps.restore(req.archive)
        # 另外三个实例也各重读一次：`restore()` 内部只刷新了它自己那一个的
        # 内存态（`_load_or_rebuild` 是实例方法），覆盖是四个族一起发生的。
        for store in (self._objects, self._summaries, self._knowledge):
            store.reload()
        self._sync_max_caches()
        return FromHarnessToMemoryToolRestoreMemoryResp(unpacked=unpacked)

    # ---- 情景记忆：episodic（单步，全量，不检索） ----

    def query_act_memories(
        self, req: FromHarnessToMemoryToolQueryActMemoriesReq
    ) -> FromHarnessToMemoryToolQueryActMemoriesResp:
        """取这一局全部的单步情景记忆，按 step 升序。"""
        entries = self._episode_acts(req.episode_id)
        return FromHarnessToMemoryToolQueryActMemoriesResp(entries=entries)

    def query_recent_act_memories(
        self, req: FromHarnessToMemoryToolQueryRecentActMemoriesReq
    ) -> FromHarnessToMemoryToolQueryRecentActMemoriesResp:
        """取这一局最近几条情景记忆（已按 step 升序，取尾部）。"""
        assert req.limit > 0, f"limit must be > 0, got {req.limit}"
        entries = self._episode_acts(req.episode_id)[-req.limit :]
        return FromHarnessToMemoryToolQueryRecentActMemoriesResp(steps=entries)

    def store_act_memory(self, req: FromHarnessToMemoryToolStoreActMemoryReq) -> None:
        """写入一条情景记忆：tool 层组装 metadata → 索引层落一个 uuid 文件。

        前置条件：`entry.step` ≥ 该局已有最大 step。
        """
        entry = req.entry
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

    def _episode_acts(self, episode_id: str) -> list[ActMemory]:
        """等值筛（episode_id）→ 解析 payload → 按 step 数值升序。"""
        assert episode_id, "episode step query needs a non-empty episode_id"
        entries: list[ActMemory] = []
        for _uuid, _meta, payload, _text in self._steps.get_many(
            self._steps.filter({"episode_id": episode_id})
        ):
            try:
                entries.append(ActMemory.model_validate(payload))
            except ValidationError:
                continue
        return sorted(entries, key=lambda m: m.step)

    # ---- task 记忆（一层一条，介于按键记忆与跨局摘要之间） ----

    def query_task_memories(
        self, req: FromHarnessToMemoryToolQueryTaskMemoriesReq
    ) -> FromHarnessToMemoryToolQueryTaskMemoriesResp:
        """取这一局的全部 task 记忆，按 start_step 升序。"""
        assert req.episode_id, "task memory query needs a non-empty episode_id"
        memories: list[TaskMemory] = []
        for _uuid, _meta, payload, _text in self._tasks.get_many(
            self._tasks.filter({"episode_id": req.episode_id})
        ):
            try:
                memories.append(TaskMemory.model_validate(payload))
            except ValidationError:
                continue
        return FromHarnessToMemoryToolQueryTaskMemoriesResp(
            memories=sorted(memories, key=lambda m: m.start_step)
        )

    def store_task_memory(self, req: FromHarnessToMemoryToolStoreTaskMemoryReq) -> None:
        """落库一条 task 记忆：tool 层组装 metadata → 索引层落一个 uuid 文件。"""
        m = req.memory
        self._tasks.put(
            metadata={
                "run_id": m.run_id,
                "episode_id": m.episode_id,
                "task_id": m.task_id,
                "start_step": str(m.start_step),
            },
            payload=m.model_dump(),
            text=m.summary,
        )

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
        读两次拿到同一个顺序（`LocalMemoryStore.filter` 的交集走 `set`，本身无序）。
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
          一条 task 记忆）。它不是"蒸馏的降级"，而是那种局在记忆里唯一的
          痕迹；写入点是 `episode/episode_done/leave_chapter.py::store_empty_chapter()`，它保证
          **每局恰好留一条**。**没有标记位**（0914 99 删了 `chapter_only`）——
          空不空看 `markdown` / `summary` 自己。

        落盘形态：`memory/episode_memory/<uuid>.md`——frontmatter 是结构化
        元数据，正文是蒸馏出的 markdown。**文件用 uuid 命名**（`filename`
        这个模型字段 0914 98 已整个删掉——它在 uuid 命名落地那天就没有读方了）。
        写完按 `max_summaries` 裁剪：超限淘汰质量最差的，
        **删掉**（`delete_many`；0916 之前是搬进 voided 归档）。

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
        先走。淘汰 = 直接删（0916；此前是搬进 `voided-<ts>/` 归档，那套已废
        ——要留档请先 `snapshot()`）。"""
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
        self._summaries.delete_many([worst])

    # ---- 语义记忆：object（交互事件流的透传，判定在 harness） ----

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        """取本 run（`req.run_id`）的交互事件，按 step 升序，直接返回不做折叠。

        `map_id` 为 None = **不按地图筛**（0914 S2 放开）：run 级消费方（`plan`）
        没有"当前地图"，要的是本 run 涉及过的地图上的全部事实。`before_step` 是
        **区间条件**，不进索引交集（索引层不认识"大于"）——等值条件先筛小，
        再在这里数值收尾"检索不读未来"。
        """
        conditions = {"run_id": req.run_id}
        if req.map_id is not None:
            conditions["map_id"] = str(req.map_id)
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

        前置条件：每个事件的 step ≥ 其所在局已有最大 step。
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

        知识由人管理（自动抽取已删），记录由调用方组装好；本方法只做三件事：
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
