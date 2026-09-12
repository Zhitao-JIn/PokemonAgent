"""tools 层的四张对外契约：`BrainToolPort`/`GameToolPort`/`MemoryToolPort`/
`TraceToolPort`——harness 认识的工具门面。

（曾是五张：`CheckpointToolPort` 已在步 5b 解散——存档不再是「外面递进来的一根 Port」，
而是 harness 自己的状态模型 `EpisodeCheckpoint` 的落盘能力，只剩
`HarnessDeps.checkpoint_root` 一条路径的身份。）

原来分别放在顶层 `pokemon_agent/interfaces/tools/`，跟 `memory/ports.py`
同一个道理搬到了这里：这四张 Port 全部只依赖 `schemas.harness` 的信封类型，
没有自己专属的 domain schema（跟 `world`/`trace`/`providers`/`brain` 不同，
不需要开一个 `interface/` 子包分协议和数据形状），所以走扁平的 `ports.py`，
跟实现文件（`brain_tool.py`/`game_tools.py`/`memory_tool.py`）同住 `tools/`
包顶层（trace 那一个已收成 `tools/trace/` 包，分派器 + `render.py` +
`model_calls.py`，见 D8-③；checkpoint 那一个已在步 5b 解散进 harness，不再有实现文件）。

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
为什么必须懒加载：那两个都有真的回环）。迁移理由与验收见
`docs/spec/tools/PLAN_tool_interface.md`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolVerifyAndSummarizeReq,
    FromHarnessToBrainToolVerifyAndSummarizeResp,
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateBytesReq,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateBytesResp,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSetTaskReq,
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
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolReadDiskEventsReq,
    FromHarnessToTraceToolReadDiskEventsResp,
    FromHarnessToTraceToolVoidAfterReq,
)


@runtime_checkable
class BrainToolPort(Protocol):
    """harness 认识的"大脑工具"——跟 `Brain` 之间的翻译门面。

    跟 `GameToolPort`/`MemoryToolPort` 同一类——harness 的三根依赖(brain/trace/
    tools)之一（tools 集合的成员）；不同的是它不做"外部系统原始结构→契约"的
    转换，因为 `Brain` 自己已经吃干净了跟 LLM provider 之间的转换。它做的是
    **另一件事**：把 harness 自己的契约(`BrainTool*Req`/`Resp`)跟 `Brain` 的
    原生契约(`ChooseOnceReq` 等)显式互转——两跳各自独立的形状，即使今天
    翻译就是原样转发，也不能让 harness 直接拿 `BrainPort` 用，那样两边的契约
    会被绑死成同一份。

    方法名跟 `BrainPort` 一一对应(choose_once/judge/reflect/verify_and_summarize/
    plan_once)，故意不改名——方便对照哪个 tool 方法在转发哪个 brain 方法；
    真正不同的是每个方法收发的类型，全部换成 `schemas/communication/brain_tool_*.py`
    里定义的这一跳专属 Req/Resp。
    """

    def choose_once(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """转发一次决策尝试。失败：抛 `DecisionAttemptFailed`（同 `BrainPort`）。"""
        ...

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """转发一次判定。永远返回 resp，不抛异常（同 `BrainPort`）。"""
        ...

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """转发一次反思。"""
        ...

    def verify_and_summarize(
        self, req: FromHarnessToBrainToolVerifyAndSummarizeReq
    ) -> FromHarnessToBrainToolVerifyAndSummarizeResp:
        """转发一次校验+蒸馏。永远返回 resp，不抛异常（同 `BrainPort`）。"""
        ...

    def plan_once(
        self, req: FromHarnessToBrainToolPlanOnceReq
    ) -> FromHarnessToBrainToolPlanOnceResp:
        """转发一次 run 级规划尝试。失败：抛 `PlanAttemptFailed`（同 `BrainPort`）。"""
        ...


@runtime_checkable
class GameToolPort(Protocol):
    """Harness 操作世界的接口：执行、开局、存档。

    这是第一跳（harness → 门面），入参与返回一律是信封；门面往里调 world
    走裸参数，那一跳不造信封。
    """

    def save_state(self, req: FromHarnessToGameToolSaveStateReq) -> None:
        """把世界当前状态存成文件。

        req.path：存档文件路径。
        """
        ...

    def save_state_bytes(self) -> FromHarnessToGameToolSaveStateBytesResp:
        """把世界当前状态存成字节串（checkpoint 每步世界快照用）。"""
        ...

    def load_state_bytes(self, req: FromHarnessToGameToolLoadStateBytesReq) -> None:
        """从字节串恢复世界状态（checkpoint 恢复用）。

        req.emulator_state：要回载的世界快照字节。
        """
        ...

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """按当前 overlay 给出此刻能按的键。

        req.observation：当前观测。
        后置条件：resp.action_space.names 非空。
        """
        ...

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> None:
        """执行一个动作，推进世界。**不感知**——调用方另调 `perceive_once()` 拿新观测。

        req.action：要执行的动作。**执行粒度是一个键**（单段、`times=1`）——
            连按已经在 Harness 的循环里展开成一步一步。
        req.observation：这个动作据以选出的那份观测。
        req.settle：按完要不要等世界把过场走完（链中间的键不等，见该字段说明）。
        前置条件：动作的按键属于 get_action_space(req.observation) 的结果（实现方 assert）。
        """
        ...

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """按任务重置到初始状态。**不感知**——调用方另调 `perceive_once()` 拿第一帧。

        req.task：要跑的任务。
        前置条件：req.task.max_steps > 0。
        """
        ...

    def set_task(self, req: FromHarnessToGameToolSetTaskReq) -> None:
        """只挂任务标记，**不动模拟器状态**（checkpoint 恢复后配 `load_state_bytes` 用）。

        req.task：要接上跑的任务。
        前置条件：req.task.max_steps > 0；`load_state_bytes()` 已经把模拟器摆到了正确的帧。
        """
        ...

    def perceive_once(self, *, ram_only: bool = False) -> FromHarnessToGameToolPerceiveOnceResp:
        """感知当前这一帧。

        `ram_only=False`：**只问一次视觉模型，不重试**。
        调用方在 `reset()`/`execute()` 之后调它拿观测；重试预算与循环归
        调用方（Harness）管，见 `docs/ROADMAP.md`。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）。

        `ram_only=True`：**不调视觉模型**，只读内存里确定的那几样（坐标、朝向、
        地标、通行图、地图编号）——链中间的键用这一档，它们只需要判"位置动没动、
        换没换图"。返回的观测 `perceived=False`：场景与对话**不是空的，是没读过**；
        `calls` 为空，也不会失败。

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

        req.events：harness 判定层
        （`harness/episode/store/store_object_semantic_memory/rules.py`）构造好的事件。
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


@runtime_checkable
class TraceToolPort(Protocol):
    """事件流的记账与读取。

    两个写方法是同一条分工——**harness 只组装信封（挑字段、声明来源），拆解
    规则全在 tool 层**：
    - `append`：一笔账 → 按 `kind` 渲染 payload，必要时一拆多；
    - `append_model_calls`：一次模型交互的 N 次尝试 → N 条 `MODEL_CALL`。

    读方法跟 `TracePort` 一一对应：`cursor` / `read_disk_events` 原样转发
    （调用方拿存储形状 `TraceEvent`）。

    **签名只用信封，不用任何模块的领域类型**：这是本文件所有端口共守的边界
    （见模块 docstring 与 `docs/PLAN_tool_interface.md`）。所以"一次交互的尝试账"
    在签名里是 `FromHarnessToTraceToolAppendModelCallsReq`，而不是那个裸的
    `ModelCallLog`。

    **边界不对称**：写者只有 harness（走本端口）；读者是 api
    （运维侧，直读 `TracePort`/`LocalTrace`，不进 tool 层）。
    """

    def append(self, req: FromHarnessToTraceToolAppendReq) -> int:
        """记一笔账，返回最后一条事件分到的 event_id。

        前置条件：req.kind 对应渲染所需字段非空（tool 入口 assert）。
        后置条件：渲染出的全部事件已落盘；返回的 event_id 严格大于此前
            任何一次 append 的值（一次 req 可能展开成多条事件，如
            `model_call` 的账单 + 失败补 ERROR）。
        """
        ...

    def append_model_calls(self, req: FromHarnessToTraceToolAppendModelCallsReq) -> None:
        """记一次模型交互的**全部尝试**：一笔交互 → N 条 `MODEL_CALL`。

        跟 `append` 同一分工——调用方只组装信封（定位字段 + `source` + 原始尝试账），
        "每条带什么 `attempt`、怎么落"是 tool 的处理。

        前置条件：`req.log` 按 `attempt` 升序（重试循环保证）。
        后置条件：`req.log` 里每一条都已落盘；空 log 合法且不写任何事件
            （`ram_only=True` 的感知压根没调模型）。
        """
        ...

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（checkpoint 快照用）。"""
        ...

    def read_disk_events(
        self, req: FromHarnessToTraceToolReadDiskEventsReq
    ) -> FromHarnessToTraceToolReadDiskEventsResp:
        """读盘上全部事件（checkpoint 恢复的主前缀来源，event_id 升序）。"""
        ...

    def void_after(self, req: FromHarnessToTraceToolVoidAfterReq) -> list[str]:
        """把游标之后的事件作废（原地打 `valid=false`），返回**整局废弃**的局列表。

        打标与「哪些局只活在游标之后」都是存储层的知识（见 `TracePort.void_after`），
        本层原样转发；"拿这份名单去作废哪些记忆、哪些存档"是恢复语义，归调用方
        （`episode_entry.void_timeline`）。

        前置条件：`req.cursor` ≥ -1（调用方已完成对账）。
        后置条件：游标之后的事件全部 `valid=false`（已废弃的不重复写）；返回的局
            在废弃时间线里整局作废。
        """
        ...
