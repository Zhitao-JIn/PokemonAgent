"""tools 层的四张对外契约：`BrainToolPort`/`GameToolPort`/`MemoryToolPort`/
`TraceToolPort`——harness 认识的工具门面。

（曾是五张：`CheckpointToolPort` 已在步 5b 解散；遗留的存档相关方法与信封
也随后整体删除——见 `CHANGELOG.md` 2026-09-13 第 57 条。）

原来分别放在顶层 `pokemon_agent/interfaces/tools/`，跟 `memory/ports.py`
同一个道理搬到了这里：这四张 Port 全部只依赖 `schemas.harness` 的信封类型，
没有自己专属的 domain schema（跟 `world`/`trace`/`providers`/`brain` 不同，
不需要开一个 `interface/` 子包分协议和数据形状），所以走扁平的 `ports.py`，
跟实现文件（`brain_tool.py`/`game_tools.py`/`memory_tool.py`）同住 `tools/`
包顶层（trace 那一个已收成 `tools/trace/` 包，分派器 + `render.py`，
见 D8-③；批量账文件 `model_calls.py` 0916 随写口统一删除）。

零循环依赖风险：`schemas.harness` 对 `tools/` 没有反向依赖，这四张 Port
可以放心立即加载，不需要懒加载。

**上面那段的后半截已经过期（2026-09-12）。** 事实部分今天依然成立——只依赖
信封、没有专属 domain schema、仍然不预建 `interface/domain/`；过期的是**结论**：
当时把"扁平"当成了"协议与实现平级、同一个出口一起导出"，而问题从来不在文件
放在哪一级，在**出口**。`tools/__init__.py` 是"进这一层的门"，出口同时导出
协议和实现，就意味着拿一张协议也会把五个插件全带上（实测 146 个
`pokemon_agent` 模块）。所以本文件搬进了 `tools/interface/`——**内容零改动，
只换了住址和出口**：协议改由 `tools/interface/__init__.py` 单独导出，实现改由
收窄且懒加载的 `tools/__init__.py` 导出。

那句"零循环依赖、不需要懒加载"今天**仍然有效**，而且正是这次搬家的安全保证
——`schemas.harness` 不会回头要 `tools/` 的任何东西，所以本包仍然全部立即
导入，不做 `__getattr__`（对照 `harness/interface` 与 `world/interface`
为什么必须懒加载：那两个都有真的回环）。现状见 `docs/spec/tools/SPEC.md` 一、二节。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolExtractReq,
    FromHarnessToBrainToolExtractResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolResetReq,
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
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolRestoreMemoryResp,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryResp,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryResp,
    FromHarnessToMemoryToolStoreKnowledgeReq,
    FromHarnessToMemoryToolStoreKnowledgeResp,
    FromHarnessToTraceToolAppendReq,
    ModelCallLog,
    TraceEvent,
)


@runtime_checkable
class BrainToolPort(Protocol):
    """harness 认识的"大脑工具"——跟 `Brain` 之间那层翻译壳的契约。

    **它守的是两个互不认识的世界的边界**：harness 侧是装满了
    `Observation`/`ActionSpace`/`StepMemory` 的信封；brain 侧只认 prompt 文本
    与一撮裸字段。这一层负责渲染、世界语义规范化、盖章坐标、重试循环与
    组装存储形状——**这些没有一件是 brain 该知道的**。

    跟 `GameToolPort`/`MemoryToolPort` 同一类——harness 的三根依赖之一。
    方法名刻意**不加 `once` 后缀**（`choose` 而不是 `choose_once`）：重试循环
    已经下沉到这一层，harness 调的就是"一次完整决策（含重试）"，
    加 `once` 名不副实。
    """

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """一次完整决策：渲染 → 重试 → 规范化。

        失败：重试用尽时抛 `MaxRetriesExceeded`（账在异常里）。
        """
        ...

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """转发一次判定。永远返回 resp，不抛异常。"""
        ...

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """一次反思：渲染两帧 → 调大脑 → 盖章坐标、组装 `StepMemory`。"""
        ...

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """校验本局 step 记忆哪些可信。永远返回 resp，不抛异常。

        **不过滤**——`verdicts.index` 对应 `req.entries` 的下标，调用方自己筛。
        """
        ...

    def summarize(
        self, req: FromHarnessToBrainToolSummarizeReq
    ) -> FromHarnessToBrainToolSummarizeResp:
        """把本局过滤后的可信 step 记忆蒸馏成一条摘要，并组装 `EpisodeMemory`。
        永远返回 resp，不抛异常。"""
        ...

    def plan(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        """一次完整规划（含重试）。失败：重试用尽时抛 `MaxRetriesExceeded`（账在异常里）。"""
        ...

    def extract(self, req: FromHarnessToBrainToolExtractReq) -> FromHarnessToBrainToolExtractResp:
        """一次世界知识抽取：渲染这一局的记录 → 调大脑 → **组装存储形状**。

        跟 `summarize` 是同一分工的两半——`extract` 在这里干的活和
        `summarize` 逐字同形（渲染、重试、盖来源章），只是产物不同：那边装
        `EpisodeMemory`（属于那一局），这边装 `KnowledgeRecord`（属于世界，
        `req.run_id`/`req.episode_id` 只是来源）。所以两个方法**不共用实现**，
        但共用同一份素材形状（`req.entries`）——那是两条链路的输入契约。

        **空列表不是失败**：`resp.records == []` 表示"这一局什么都没读到"，
        那是常态。失败只有一种——重试用尽抛 `MaxRetriesExceeded`
        （`source="extract"`，账在异常里），由调用方决定这一局的收场。
        """
        ...


@runtime_checkable
class GameToolPort(Protocol):
    """Harness 操作世界的接口：执行、开局、感知。

    这是第一跳（harness → 门面），入参与返回一律是信封；门面往里调 world
    走裸参数，那一跳不造信封。

    **存档一族已删**（`save_state` / `save_state_bytes` / `load_state_bytes` /
    `set_task`）：它们只服务 checkpoint 与它的恢复链，随恢复链一起删掉了
    （见 `CHANGELOG.md` 2026-09-13 第 57 条）。`world` 层自己仍保留这些能力面，本 Port
    只是不再向 harness 暴露——"这个 run 用什么存档"是 harness 的取舍，
    不该裁剪 `world` 这个独立第三方模块的能力。
    """

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """按当前 overlay 给出此刻能按的键。

        req.observation：当前观测。
        后置条件：resp.action_space.names 非空。
        """
        ...

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> None:
        """执行一个动作，推进世界。**不感知**——调用方另调 `perceive_with_retry()` 拿新观测。

        req.action：要执行的动作。**执行粒度是一个键**（单段、`times=1`）——
            连按已经在 Harness 的循环里展开成一步一步。
        req.observation：这个动作据以选出的那份观测。
        req.settle：按完要不要等世界把过场走完（链中间的键不等，见该字段说明）。
        前置条件：动作的按键属于 get_action_space(req.observation) 的结果（实现方 assert）。
        """
        ...

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """按任务重置到初始状态。**不感知**——调用方另调 `perceive_with_retry()` 拿第一帧。

        req.task：要跑的任务。
        前置条件：req.task.max_steps > 0。
        """
        ...

    def perceive_with_retry(
        self, *, ram_only: bool = False
    ) -> tuple[FromHarnessToGameToolPerceiveOnceResp, ModelCallLog]:
        """感知当前这一帧——**重试循环与异常翻译都在实现方**（0913 夜定案）。

        `ram_only=False`（缺省）：反复问视觉模型，直到成功或预算耗尽。
        harness 只负责**落账**：成功用返回的 `log`，耗尽用异常携带的 `calls`
        ——两侧分工与 `BrainToolPort` 那六条链路逐字相同（见 `think_action`）。
        失败：预算耗尽抛 `MaxRetriesExceeded`（`source="perception"`）。
            **`PerceptionAttemptFailed` 不是本协议的词汇**——那是 world 的内部
            细节，被实现方在桥上接住、翻译掉了，跨不过这层。

        `ram_only=True`：**不调视觉模型**，只读内存里确定的那几样（坐标、朝向、
        地标、通行图、地图编号）——链中间的键用这一档，它们只需要判"位置动没动、
        换没换图"。返回的观测 `perceived=False`：场景与对话**不是空的，是没读过**；
        `log` 为空，也不会失败、不会重试。

        后置条件：resp.observation 非空；step 未盖章（Harness 的事）。
        """
        ...

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """**无输入**推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。

        和按键后的演化是同一回事，只是独立于按键被调用：harness 在等决策 LLM
        返回时用它填空闲窗口，让画面/音乐继续（见 `episode_harness.think`）。

        前置条件：req.frames >= 0。
        调用方要保证：这段演化不破坏"观测-决策"一致性——决策期间世界变化是
        **刻意接受的取舍**（决策基于稍早的快照，错位由下一步感知修正），
        感知/判定期间**不能**调用本方法（那要求快照稳定）。
        """
        ...


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
        """按元数据等值过滤取跨局摘要——**这一跳不做任何领域规则**（0914 定案）。

        req.conditions：字段→值，AND 取交集；空字典 = 全取。字段名与取值都由
            调用方定，这一层不解释（store 只支持等值/成员匹配，不支持范围比较）。
        前置条件：无——不过滤是合法用法，不是错误输入。
        后置条件：返回**全部**命中记录的完整 `EpisodeMemory`，**不排序、不截断、
            不限 run**；顺序只保证"同一个库读两次一样"（按 `episode_id` 字典序），
            不含相关性含义。

        **原先的四件套已删**（场景通配匹配 / 相关性排序 / 条数截断 / 跨 run 禁令）：
        它们都是消费方的判断，住在读口上等于把"取哪些、取几条"从消费方手里拿走。
        现在的分工是——读口给全集，消费方自己决定相关性与裁剪。
        """
        ...

    def store_episode_summary(
        self, req: FromHarnessToMemoryToolStoreEpisodeSummaryReq
    ) -> FromHarnessToMemoryToolStoreEpisodeSummaryResp:
        """落库一条**已经组装好**的跨局摘要，不调模型。

        蒸馏与组装都在 `BrainTool.summarize()` 里完成（resp.episode_memory，
        见 ROADMAP 16），这个方法只做落盘 + 更新检索向量缓存。
        **这是这个 Port 上唯一的跨局摘要写入口**——它接两种形态：常规的
        "蒸馏正文"，以及"正文全空"（这一局没有可蒸馏的正文，落一条只有来源章
        的记录——`harness/run/nodes/review.py::_leave_chapter()`）。
        **没有"不经校验全量蒸馏"的兜底入口**。

        req.memory：组装好的摘要记忆。
        前置条件：req.memory.episode_id 非空；正文与章自洽（要么整条完整、
            要么整条为空）。
        后置条件：resp.memory 是原对象（落库后检索索引同步更新）。
        """
        ...

    # ---- 语义记忆（object 交互事件流） ----

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        """取交互事件，按 step 升序。

        req.map_id：地图编号；**None = 不按地图筛**（run 级消费方没有"当前地图"）。
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

        req.events：harness 判定层
        （`harness/episode/store/store_object_semantic_memory/rules.py`）构造好的事件。
        前置条件：每个事件的 step ≥ 其所在局已有最大 step。
        """
        ...

    # ---- 语义记忆（知识库：离线先验 + run 期间学到的，和坐标无关） ----

    def query_knowledge(
        self, req: FromHarnessToMemoryToolQueryKnowledgeReq
    ) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        """从知识库里检索出和 req.query 相关的那几条。

        **库里住着两种来源、一种形状**：离线灌入的手写先验（metadata 里
        `source` 是文件名）与 run 期间由 `store_knowledge` 写进去的
        （`source` 是 `{run_id}/{episode_id}`）。读口不区分它们——检索时
        两边平权，谁更相关谁排前面；要分是分得开的（`resp.sources` 带了
        `source`），但那是调用方的判断，不是这一跳该做的事。

        req：一次检索请求（检索文本 + 条数上限）。
        前置条件：req.query 非空；req.limit > 0。
        后置条件：返回 contents 和 sources；无命中时都是空列表。
        """
        ...

    def store_knowledge(
        self, req: FromHarnessToMemoryToolStoreKnowledgeReq
    ) -> FromHarnessToMemoryToolStoreKnowledgeResp:
        """落库一批**已经组装好**的世界知识，不调模型。

        组装在 `BrainTool.extract()` 里完成（`resp.records`，来源章同
        `summarize` 的五个字段那一套——`source`/`run_id`/`episode_id` 由 tool
        层盖）。本方法只做**判重 + 落盘 + 更新检索向量缓存**。

        **判重在这一跳做**：同 `topic` 且正文逐字相同的条目跳过——同一件事被
        两局分别学到时不该在库里堆第二份。判据只看"完全一样"，不做语义去重：
        相近但不完全相同是**该留下**的（世界知识的措辞差异常常带着新信息），
        要不要合并是人的判断，不是存储层的。

        req.records：**空列表是合法输入**（这一局什么都没读到）——那一跳
            什么都不做，不是错误。
        前置条件：每条 record 的 `topic`/`content`/`source` 非空。
        后置条件：`resp.stored` 是**真的落库了的那几条**，是 `req.records`
            的子序列（判重跳过的那些不在里面）；顺序与 `req.records` 一致。
        """
        ...

    # ---- 快照（0916：整库存档 + 覆盖恢复） ----

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        """把**整个记忆库**打成一个 zip，返回它的路径。

        取代了原先的"归档"（`archive_many` 把记录搬进 `voided-<ts>/<kind>/`）：
        那套要的是"淘汰时留个档"，而这个要的是"能把整个库整体还原回去"——后者
        才真的有用（前者只是不删而已，且散成一堆文件）。

        **打的是整个库、不是某一族**：四族共用一个 `memory/` 根，存档的语义单位
        就是那个根。

        **zip 落在哪由实现方决定**：签名只有 `req.name`——"快照放哪个目录、叫
        什么后缀"不是 harness 该知道的事（此前那套归档让 harness 拼
        `voided-<ts>/<kind>/` 的路径，是把存储布局漏了出去）。

        req.name：快照名（文件名，不含路径分隔符）；同名覆盖。
        前置条件：req.name 非空且不含路径分隔符。
        后置条件：resp.archive 是盘上存在的 zip，里面装着各 kind 子目录的
            记录文件与 `index.json`。
        """
        ...

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        """用一个 zip 把记忆库**还原到那一刻**——以 zip 为准。

        **库里多出来的记录会被删掉**：zip 里有的按 zip 写（同名直接盖），zip 里
        没有的记录文件从库里消失。语义单位是**整个库**，不是"往库上叠一层"
        ——后者做不到"恢复到某个存档"（越恢复越多）。

        **签名收路径而不是名字**（与 `snapshot_memory` 不对称）：恢复要能接受
        任意 zip——"拿更早的一份、或者别人给的档灌回来"正是它的价值所在。

        req.archive：要恢复的 zip 路径。
        前置条件：req.archive 是盘上存在的文件。
        后置条件：resp.unpacked 是解出的文件数；实现方必须让四族的内存索引与盘上
            重新一致（否则被删掉的记录会从旧索引里冒出来）。
        失败：文件不存在、不是合法 zip 时原样抛出，不静默吞掉。
        """
        ...


@runtime_checkable
class TraceToolPort(Protocol):
    """事件流的记账与读取——**harness 认识 trace 的唯一入口**。

    写只有 `append` 一个口——**harness 只组装信封（挑字段、声明账名与来源），
    拆解规则全在 tool 层**：一笔账 → 按 `kind` 渲染正文，必要时一拆多；
    调用账的 `calls` 交**整条重试链**（每次尝试一条），渲染时逐条落成
    `*_call` 账。批量口 `append_model_calls` 0916 删了：它与 `append`
    落盘效果相同，两套并存只是写法漂移。

    **读方法也在这张端口上**：`read_events`。**边界从此对称**——
    写者与读者都只有 tool 层，harness / api 一律不 import `pokemon_agent.trace`。
    原 `cursor` / `read_disk_events` / `void_after` 三件是 checkpoint 存档与恢复
    专用，随恢复链一起删掉了（见 `CHANGELOG.md` 2026-09-13 第 57 条）；
    `read_screenshot` 随截图副本删（0913 晚）；`read_event(id)` 随
    `frame_png` 一起删（0914 封套改造——画面真源已是 `memory/step_memory/`）。
    剩下的一条是**通用读**，不做掩码、不做游标、不打标。

    **磁盘账本是唯一真相**（0913 晚）：`RunDataCenter` 的内存事件槽已删，
    run 内的节点（`plan`/`review`）现在读这里的 `read_events`，不再有
    "内存一份、盘上一份"的双写（另一个读者 SSE 端点随 `api.py` 一起删了）。

    **签名只用信封与契约层类型，不用任何模块的领域类型**：这是本文件所有
    端口共守的边界（见模块 docstring 与 `docs/spec/tools/SPEC.md`）。
    调用账在签名里就是 `FromHarnessToTraceToolAppendReq`（`calls` 字段交
    `list[ModelCall]`，裸类型只作为它出现在签名里）；返回的事件是
    `TraceEvent`（契约层），而不是 trace 自己的 `Event`。
    """

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        """记一笔账，落盘（一笔 req 可能展开成多条事件）。

        前置条件：`req.meta` 带 `source`/`episode_id`/`step` 三件（签名信息由
            harness 一次交齐）、`req.kind` 对应渲染所需
            字段非空（tool 入口 assert）。
        后置条件：渲染出的全部事件已落盘；每条的封套 `kind` 就是 `req.kind`
            ——**例外是连带产出的错误账**（某个调用失败的尝试会补一条
            `call_failed`，`type=error`）。
        """
        ...

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """读**磁盘账本**上的全部事件，按 `(ts, uuid)` 升序；可按签名做交集筛选。

        meta：`None`（或空 dict）= 不过滤，返回落盘根下的全部事件；给了就只返回
            **每个键都相等**的那批（键取 `run_id` / `source` / `episode_id` /
            `step`）。语义是 **AND-of-equalities**（各条件的候选集取交集），
            **不支持 OR、不支持大小比较**。
            落盘**不按 run 分层**（0916），所以 `run_id` 是切片的主键——
            `{"run_id": …, "episode_id": …}` 就是"这一局"。
        后置条件：按 `(ts, uuid)` 严格升序；无匹配时返回空列表（不抛异常）。
        失败：磁盘读取失败原样抛出——本方法不吞这一类错。
        """
        ...
