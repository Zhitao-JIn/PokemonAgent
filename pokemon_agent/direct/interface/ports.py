"""tools 层的对外契约：`GameToolPort`/`MemoryToolPort`/`TraceToolPort` 三张整口，
外加 brain 那族按能力拆开的**八张单方法口**（`PlanPort`/`DecomposePort`/`ChoosePort`/`JudgePort`/
`ReflectPort`/`VerifyPort`/`SummarizePort`/`TaskSummarizePort`）——harness 认识的工具门面。

（曾是五张整口：`CheckpointToolPort` 已在步 5b 解散；`BrainToolPort` 七方法总口
0922 185 按能力拆开——一个接口方法超 6 个就该拆，且"按消费方切口"后，runtime 字段
能写成 `planner: PlanPort` 这类窄类型，"不属于本层的方法"在类型上就调不出来。）

原来分别放在顶层 `pokemon_agent/interfaces/tools/`，跟 `memory/ports.py`
同一个道理搬到了这里：这四张 Port 全部只依赖 `schemas.harness` 的信封类型，
没有自己专属的 domain schema（跟 `world`/`trace`/`providers`/`brain` 不同，
不需要开一个 `interface/` 子包分协议和数据形状），所以走扁平的 `ports.py`，
跟实现文件（`brain_tool.py`/`game_tools.py`/`memory_tool.py`）同住 `tools/`
包顶层（trace 那一个已收成 `direct/trace/` 包，分派器 + `render.py`，
见 D8-③；批量账文件 `model_calls.py` 0916 随写口统一删除）。

零循环依赖风险：`schemas.harness` 对 `tools/` 没有反向依赖，这四张 Port
可以放心立即加载，不需要懒加载。

**上面那段的后半截已经过期（2026-09-12）。** 事实部分今天依然成立——只依赖
信封、没有专属 domain schema、仍然不预建 `interface/domain/`；过期的是**结论**：
当时把"扁平"当成了"协议与实现平级、同一个出口一起导出"，而问题从来不在文件
放在哪一级，在**出口**。`tools/__init__.py` 是"进这一层的门"，出口同时导出
协议和实现，就意味着拿一张协议也会把五个插件全带上（实测 146 个
`pokemon_agent` 模块）。所以本文件搬进了 `direct/interface/`——**内容零改动，
只换了住址和出口**：协议改由 `direct/interface/__init__.py` 单独导出，实现改由
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
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeRunResp,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolSummarizeTaskResp,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSaveStateResp,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolRestoreMemoryResp,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryResp,
    FromHarnessToTraceToolAppendReq,
    TraceEvent,
)


@runtime_checkable
class PlanPort(Protocol):
    """run 层的规划口：`BrainTool.build(plan=…)` 组装的 `Planner` 满足它。"""

    def plan(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        """一次完整规划（含重试）。失败：重试用尽时抛 `MaxRetriesExceeded`（账在异常里）。"""
        ...


@runtime_checkable
class DecomposePort(Protocol):
    """拆解口：`Decomposer` 满足它。episode 层 `plan_episode` 在任务链空时问一次。"""

    def decompose(
        self, req: FromHarnessToBrainToolDecomposeReq
    ) -> FromHarnessToBrainToolDecomposeResp:
        """把本局目标拆成一版任务链：渲染 → 重试 → 解析。

        失败：重试用尽时抛 `MaxRetriesExceeded`（账在异常里）。
        """
        ...


@runtime_checkable
class ChoosePort(Protocol):
    """决策口：`Chooser` 满足它。episode 层用全量 space；task 层的 `plan_task`
    是同一个方法、受限 space（`TaskRuntime.chooser` 是独立实例，可换策略）。"""

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """一次完整决策：渲染 → 重试 → 规范化。

        失败：重试用尽时抛 `MaxRetriesExceeded`（账在异常里）。
        """
        ...


@runtime_checkable
class JudgePort(Protocol):
    """判定口：`Judger` 满足它。"""

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """转发一次判定。永远返回 resp，不抛异常。"""
        ...


@runtime_checkable
class ReflectPort(Protocol):
    """反思口：`Reflector` 满足它。本链路不调模型、无重试。"""

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """一次反思：过滤存储盲区，用结构化观测 + 坐标组装 `ActMemory`（不经大脑）。"""
        ...


@runtime_checkable
class VerifyPort(Protocol):
    """校验口：`Verifier` 满足它。"""

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """标记 entries 的正/负样本（行为/总结符不符合 goal）。永远返回 resp，不抛异常。

        **不过滤**——`verdicts.index` 对应 `req.entries` 的下标，调用方自己筛。
        """
        ...


@runtime_checkable
class SummarizePort(Protocol):
    """蒸馏口：`Summarizer` 满足它。"""

    def summarize(
        self, req: FromHarnessToBrainToolSummarizeReq
    ) -> FromHarnessToBrainToolSummarizeResp:
        """把本局过滤后的正样本 step 记忆蒸馏成一条摘要，并组装 `EpisodeMemory`。
        永远返回 resp，不抛异常。"""
        ...


@runtime_checkable
class TaskSummarizePort(Protocol):
    """task 蒸馏口：`TaskSummarizer` 满足它。task 层的 `task_done` 用。"""

    def summarize_task(
        self, req: FromHarnessToBrainToolSummarizeTaskReq
    ) -> FromHarnessToBrainToolSummarizeTaskResp:
        """把本 task 过滤后的可信 ActMemory 蒸馏成一条 TaskMemory。永远返回 resp。"""
        ...


@runtime_checkable
class GameToolPort(Protocol):
    """Harness 操作世界的接口：执行、开局、感知、存读档。

    这是第一跳（harness → 门面），入参与返回一律是信封；门面往里调 world
    走裸参数，那一跳不造信封。

    **存读档**（`save_state` / `load_state`）只服务 checkpointer（checkpoint SPEC §一）：
    存的是模拟器完整状态，文件路径由 harness 给，读写文件在本层。
    """

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """按当前 overlay 给出此刻能按的键。

        req.observation：当前观测。
        后置条件：resp.action_space.names 非空。
        """
        ...

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        """执行一个动作，推进世界。**不感知**——调用方另调 `perceive_task()` 拿新观测。

        req.action：要执行的动作。**执行粒度是一个键**（单段、`times=1`）——
            连按已经在 Harness 的循环里展开成一步一步；或**一条脚本**，world 执行到底。
        req.observation：这个动作据以选出的那份观测。
        req.settle：按完要不要等世界把过场走完（链中间的键不等，见该字段说明）。
        前置条件：动作的按键或脚本名属于 get_action_space(req.observation) 的结果（实现方 assert）。
        后置条件：脚本动作时 `resp.report` 是终态报告，按键动作时为 None。
        失败：服务端拒绝按键时抛 McpToolError；脚本业务失败由终态报告表达。
        """
        ...

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """按任务重置到初始状态。**不感知**——调用方另调 `perceive_task()` 拿第一帧。

        req.task：要跑的任务。
        前置条件：req.task.max_steps > 0。
        后置条件：世界已重置到绑定起点；服务端拒绝时抛 McpToolError，不得继续存档。
        """
        ...

    def save_state(
        self, req: FromHarnessToGameToolSaveStateReq
    ) -> FromHarnessToGameToolSaveStateResp:
        """把模拟器完整状态写到 `req.path`。**不推进世界**。

        后置条件：`resp.path` 文件存在，`resp.size` 等于写入的字节数（> 0）。
        失败：写文件失败原样抛出。
        """
        ...

    def load_state(self, req: FromHarnessToGameToolLoadStateReq) -> None:
        """从 `req.path` 读回模拟器完整状态。**不推进世界**。

        前置条件：`req.path` 是 `save_state` 写出的文件。
        失败：文件不存在或读失败原样抛出；服务端拒绝读档时抛 McpToolError。
        """
        ...

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        """感知当前这一帧（task 层）：**不调视觉模型**，只读内存与屏幕缓冲，观测带场合（`scene`）。

        不会失败、不重试、没有模型调用记录。
        后置条件：resp.observation 非空、`perceived=False`；step 未盖章（Harness 的事）。
        """
        ...

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """**无输入**推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。

        和按键后的演化是同一回事，只是独立于按键被调用。**目前没有调用方**：
        决策改成同步调用（重试循环在 `BrainTool.choose()`）之后，"等 LLM 返回时
        填空闲窗口"这件事省不出时间——不限速时世界跑得比等待快。这一格仍是契约
        的一部分，留给将来真需要"按时间推进而不感知"的场景。

        前置条件：req.frames >= 0。
        调用方要保证：这段演化不破坏"观测-决策"一致性——决策期间世界变化是
        **刻意接受的取舍**（决策基于稍早的快照，错位由下一步感知修正），
        感知/判定期间**不能**调用本方法（那要求快照稳定）。
        """
        ...


@runtime_checkable
class MemoryToolPort(Protocol):
    """Harness 读写记忆的接口：统一回忆（recall）+ 统一记忆（memorize）+ 运维快照。

    **MCP 化定案（2026-09-29）**：查询侧与写侧各收敛为一个口——调用方**不显式
    指定记忆种类**，种类由产生方天然决定、由底层分族规则圈定（同 chooser 的
    统一动作掩码：一个命名空间，调用方不选类型）。

    - `recall`：统一回忆口。`conditions` 只放上下文 hint（episode_id / map_id /
      place / run_id），**不放 kind**——hint 命中族（act/task/object 的近因序）
      在前，语义族（episode/knowledge 的相关性）在后；
    - `memorize`：统一记忆口。records 按 kind 判别落族（act/task/episode/
      object/knowledge），种类由产生方天然决定（判定层产 object 事件、蒸馏产
      summary、act 环产 act 记忆）——调用方不猜种类，只报身份；
    - `snapshot_memory` / `restore_memory`：运维快照（checkpoint 专用），
      **不进 MCP 注册表**——MCP 面只暴露 recall / memorize 两个能力。

    前置/后置条件详见各方法与 `FromHarnessToMemoryToolRecall*` /
    `FromHarnessToMemoryToolMemorize*` 信封定义。
    """

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        """统一回忆口：分族检索后融合排序，返回混合条目（每条自带 kind 身份）。

        前置条件：`req.limit >= 1`；`req.conditions` 的值全是 str。
        后置条件：`resp.items` 每条带 kind/uuid/score/content/payload；
        hint 命中族在前（族内按 step / total_acts 升序），语义族按相关性降序；
        req.limit is None 或总数 <= req.limit。
        """
        ...

    def memorize(
        self, req: FromHarnessToMemoryToolMemorizeReq
    ) -> FromHarnessToMemoryToolMemorizeResp:
        """统一记忆口：records 按 kind 判别落族，返回实际落库清单。

        前置条件：每条 record 的 payload 通过对应 schema 校验；act / object 的
        step >= 该局已有最大 step（违反 = 调用方伪造时序）。
        后置条件：`resp.stored` 是 `req.records` 的子序列（knowledge 判重跳过的
        不在其中），顺序一致。
        """
        ...

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        """把整个记忆库打成一个 zip，返回它的路径（checkpoint 专用）。"""
        ...

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        """用一个 zip 把记忆库还原到那一刻——以 zip 为准（checkpoint 专用）。"""
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

    **trace backend 是唯一真相**：`RunDataCenter` 的内存事件槽已删，
    run 内的节点（`plan`/`review`）现在读这里的 `read_events`，不再有
    "内存一份、存储一份"的双写。若 backend 最终一致，读结果可以暂时缺少新事件。

    **签名只用信封与契约层类型，不用任何模块的领域类型**：这是本文件所有
    端口共守的边界（见模块 docstring 与 `docs/spec/tools/SPEC.md`）。
    调用账在签名里就是 `FromHarnessToTraceToolAppendReq`（`calls` 字段交
    `list[ModelCall]`，裸类型只作为它出现在签名里）；返回的事件是
    `TraceEvent`（契约层），而不是 trace 自己的 `Event`。
    """

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        """记一笔账（一笔 req 可能展开成多条事件）。

        前置条件：`req.meta` 带 `source`/`episode_id`/`step` 三件（签名信息由
            harness 一次交齐）、`req.kind` 对应渲染所需
            字段非空（tool 入口 assert）。
        后置条件：渲染出的全部事件已交给所选 trace backend；每条的封套 `kind` 就是 `req.kind`
            ——**例外是连带产出的错误账**（某个调用失败的尝试会补一条
            `call_failed`，`type=error`）。
        """
        ...

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """读当前 trace backend 可见的全部事件，按 `(ended_at, seq)` 升序；可按签名做交集筛选。

        meta：`None`（或空 dict）= 不过滤，返回 backend 当前可见的全部事件；给了就只返回
            **每个键都相等**的那批（键取 `run_id` / `source` / `episode_id` /
            `step`）。语义是 **AND-of-equalities**（各条件的候选集取交集），
            **不支持 OR、不支持大小比较**。
            LocalTrace 落盘不按 run 分层（0916）；LangfuseTrace 一实例绑定一个 run。
            `{"run_id": …, "episode_id": …}` 是"这一局"的常见筛选。
        后置条件：按 `(ended_at, seq)` 严格升序；无匹配时返回空列表（不抛异常）。
        失败：所选 backend 读取失败原样抛出——本方法不吞这一类错。
        """
        ...

    def flush(self) -> None:
        """等待 backend 提交当前缓冲事件（如有）。

        本地同步存储可为空操作；Langfuse flush 仅保证 SDK 队列已发送，不保证查询 API 已可见。
        backend 的刷新失败记录为诊断信息，不改变已经完成的 harness 业务结果。
        """
        ...

    def shutdown(self) -> None:
        """关闭 backend 持有的后台资源；重复关闭必须可安全调用。

        调用方负责在 harness 生命周期结束后调用。SDK 已提供进程退出处理时，实现可以幂等委托。
        """
        ...


@runtime_checkable
class RunSummarizePort(Protocol):
    """run 蒸馏能力，输入最终素材，输出未落库记忆。"""

    def summarize_run(
        self, req: FromHarnessToBrainToolSummarizeRunReq
    ) -> FromHarnessToBrainToolSummarizeRunResp:
        """承诺以请求盖来源章；调用方保证素材非空；耗尽抛明确的预算或重试异常。"""
        ...
