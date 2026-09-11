"""tools 包的五个对外契约：`BrainToolPort`/`CheckpointToolPort`/`GameToolPort`/
`MemoryToolPort`/`TraceToolPort`——harness 认识的五张工具门面。

原来分别放在顶层 `pokemon_agent/interfaces/tools/`，跟 `memory/ports.py`
同一个道理搬到了这里：这五个 Port 全部只依赖 `schemas.harness` 的信封类型，
没有自己专属的 domain schema（跟 `world`/`trace`/`providers`/`brain` 不同，
不需要开一个 `interface/` 子包分协议和数据形状），所以走扁平的 `ports.py`，
跟实现文件（`brain_tool.py`/`checkpoint_tool.py`/`game_tools.py`/
`memory_tool.py`/`trace_tool.py`）同住 `tools/` 包顶层。

零循环依赖风险：`schemas.harness` 对 `tools/` 没有反向依赖，这五个 Port
可以放心立即加载，不需要懒加载。
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
    FromHarnessToCheckpointToolLoadReq,
    FromHarnessToCheckpointToolLoadResp,
    FromHarnessToCheckpointToolSaveReq,
    FromHarnessToCheckpointToolVoidReq,
    FromHarnessToCheckpointToolVoidResp,
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
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolReadDiskEventsReq,
    FromHarnessToTraceToolReadDiskEventsResp,
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
class CheckpointToolPort(Protocol):
    """Harness 的 checkpoint 手：存、取（三元组定位）、废弃归档。

    契约（PLAN_checkpoint v4）：签名三元组 `(run_id, episode_id, step)` 显式落在
    每份 checkpoint 的 json 里；`last_event_id` 是 trace 游标——恢复的主坐标，
    `event_id` 大于它的事件全部属于废弃时间线。只有一种落盘形态：`EpisodeRunState`
    与当时的 `RunState` 打包进同一份 `<step>.json`（无单独的 run 级文件）。
    """

    def save(self, req: FromHarnessToCheckpointToolSaveReq) -> None:
        """存一份 checkpoint（`step/<episode_id>/<step>.*`）。

        后置条件：先世界快照后 json（json 是提交点）；中途 crash 留下的是
        上一号有效 checkpoint（恢复管线按"成对存在 + 签名匹配"识别）。
        """
        ...

    def load(
        self, req: FromHarnessToCheckpointToolLoadReq
    ) -> FromHarnessToCheckpointToolLoadResp | None:
        """按三元组取一份 checkpoint；不存在（或 state/json 不成对）返回 None。

        返回值同时带 `state_dump`（EpisodeRunState）与 `run_state_dump`
        （RunState）——调用方按自己需要的那层取，不用分两次查、也不用猜
        该读哪个文件。
        """
        ...

    def void_after(
        self, req: FromHarnessToCheckpointToolVoidReq
    ) -> FromHarnessToCheckpointToolVoidResp:
        """废弃时间线处理：trace 按 cursor 截断归档、记忆层截断、截图/存档归档。

        前置条件：调用方已完成对账（快照签名/游标合法）。
        后置条件：主前缀（event_id ≤ cursor）之外无任何残留——重跑同三元组
        不会撞名、不会读到"未来"的记忆；被废弃数据全部在 voided 归档目录。
        """
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

        req.action：要执行的动作（可能是动作链）。
        req.observation：这个动作据以选出的那份观测。
        前置条件：动作每一段的按键属于 get_action_space(req.observation) 的结果（实现方 assert）。
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

    def perceive_once(self) -> FromHarnessToGameToolPerceiveOnceResp:
        """感知当前这一帧，**只问一次视觉模型，不重试**。

        调用方在 `reset()`/`execute()` 之后调它拿观测；重试预算与循环归
        调用方（Harness）管，见 `docs/ROADMAP.md`。
        后置条件：resp.perceived.observation 非空；step 未盖章（Harness 的事）。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）。
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


@runtime_checkable
class TraceToolPort(Protocol):
    """事件流的记账与读取。

    两个方法，跟 `TracePort` 一一对应：
    - `append`：harness 只组装 `FromHarnessToTraceToolAppendReq`（挑字段 + 声明
      kind），payload 字段格式、条件字段、一拆多全部是 tool 的处理；
    - `events`：读侧没有要转换的数据，原样转发（调用方拿存储形状 `TraceEvent`）。

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

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（checkpoint 快照用）。"""
        ...

    def read_disk_events(
        self, req: FromHarnessToTraceToolReadDiskEventsReq
    ) -> FromHarnessToTraceToolReadDiskEventsResp:
        """读盘上全部事件（checkpoint 恢复的主前缀来源，event_id 升序）。"""
        ...
