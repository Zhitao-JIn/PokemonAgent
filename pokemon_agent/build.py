"""全项目唯一装配点：把所有具体实现 new 起来，拼成 RunHarness 与 WorldMcpTool。

**四个独立模块（brain / world / memory / trace）的实现类，本文件一律零 import**
——各自由 tool 层上的接线工厂造好：`BrainTool.build()` / `WorldMcpTool.build()` /
`MemoryTool.build()` / `TraceTool.build()`。装配点只递裸字段（型号名、路径、开关）。
本文件对 `pokemon_agent.{brain,world,memory,trace}` 的 AST import 点都是 **0**。

想知道"怎么拼起来"读这个文件；想知道"怎么互相调用"读 harness/run/harness.py。

**入口是 run 级**：返回的 `RunHarness` 是主 agent（完整一局游戏）。三张图（run / episode / task，
各 5 格）都在本文件编译：run 图交给 `RunHarness`，episode 图挂 `RunRuntime.episode_graph`、
task 图挂 `EpisodeRuntime.task_graph`，由上一层的 `act` 格取用。
旧调用方拿到的 `harness.run(run_id, goals)` 是 run 级签名。

**装配是"造三个 runtime + 编译三张图"**：`TaskRuntime`（task 层，v1 容器先行）
→ `EpisodeRuntime`（`decomposer` / `judger` / `verifier` / `summarizer`，嵌套持有
`task`）→ `RunRuntime`（`planner` / `judger`，嵌套持有 `episode`）——
`RunHarness(run_rt, run_graph)` 只收它与 run 图，不再逐个把同样的东西再递一遍（那会有两份真源，而
"两边不是同一个对象"不报错）。`trace` / `memory` / `reviewer` / `game` 三层是
**同一实例**（复制引用）。**id 一律归 state**（186）：`run_id` 住 `RunState`，
runtime 不再复制；brain 能力**按层各造一份**（185，见下面三个 `BrainTool.build`）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pokemon_agent.config import CHECKPOINT_ENABLED, SCOPE_IMAGE_CAP, TRACE_BACKEND
from pokemon_agent.deadline import Deadline
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.direct.trace import TraceTool, assert_server_ready
from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.harness import (
    EpisodeRuntime,
    Reviewer,
    RunHarness,
    RunRuntime,
    TaskRuntime,
)
from pokemon_agent.harness.checkpoint import Checkpointer, build_saver
from pokemon_agent.harness.episode import compile_episode_graph
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.mcpclient import assert_mcp_server_ready
from pokemon_agent.mcpclient.client import McpTransportError
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.run_config import load_run_config

logger = logging.getLogger(__name__)


def build_real(
    text_model: str = "qwen-plus",
    judge_model: str = "qwen3.8-max",
    verify_model: str = "doubao-seed-2-1-pro-260628",
    plan_model: str = "doubao-seed-2-1-pro-260628",
    max_tokens: int = 25600,
    run_id: str = "local",
    trace_root: str | Path | None = None,
    trace_backend: str | None = None,
    memory_root: str | Path | None = None,
    memory_server_url: str | None = None,
    world_server_url: str | None = None,
    checkpoint_root: str | Path | None = None,
    branch: str = "main",
    live_feed_url: str | None = None,
    # 供应商由**型号名前缀**决定（0914 起，表在 `brain/providers.py::_PROVIDER_PREFIXES`）：
    # `qwen*` → DashScope、`doubao*` → 火山方舟、`deepseek*` → DeepSeek 官方 API。
    # 下面这几个缺省值因此不只是"型号名"，它们同时**选定了厂商**。
    #
    # 缺省组合的历史依据（0908 实测，见 CHANGELOG）：perception/judge 走 qwen3.8-max
    # （DashScope 图像按分辨率计费，原生 160×144 每张仅 74 tok，而 judge 每步带
    # 2-3 张历史帧）；verify/plan 留在火山方舟（豆包图像按张计费，实测恒定
    # 1294 tok/张、与分辨率无关，verify 的多帧拼接成一张后图费与帧数解耦）。
    # **这不是硬约束**：换哪家只改这几个字符串，`provider_for()` 会造出配套的类
    # ——"传 Qwen 型号名给 verify 会 404"那种事现在在装配期就变成 `ValueError`，
    # 因为型号名前缀与厂商类必须配套这件事已经由表保证。
    reviewer: Reviewer | None = None,
    config: str | Path | None = None,
) -> tuple[RunHarness, WorldMcpTool]:
    """装配真实链路；返回 `(harness, game)`。

    memory_server_url 显式参数优先于 MCP_MEMORY_SERVER_URL；缺地址抛 McpTransportError，
    有地址先检查 /health。memory_root 仅指定客户端快照根，缺省为启动目录下的 memory/。

    world_server_url 显式参数优先于 MCP_WORLD_SERVER_URL；缺地址抛 McpTransportError。
    世界仅由 server 持有，装配点返回 MCP 门面，不创建模拟器。

    **事件流不在返回值里**（0913 下午）：harness 侧全部读点走
    `Runtime.trace`（`TraceToolPort`），装配点把 `LocalTrace` 交出去只会
    逼调用方去认一个 trace 类型。`tracelog/` 落盘的路径由 tool 层持有
    （缺省 = 启动目录下的 `tracelog/`，`trace_root` 可改），外部要读账一律经
    `deps.trace`。

    `reviewer`：人与图之间的那扇门（**同步接口**，控制台实现会阻塞读 stdin）。
    不传 → `NullReviewer`（没人插话、没人推翻）。不传而无头是一个正常场景
    （测试、CI、无头批量跑），不是缺配置。

    `live_feed_url`：人在环后端地址（`ws://host:port`）；给了就把每笔账顺手推给网页实时看
    （`TraceTool.build` 里包一层 `LiveFeedTrace`）。None = 不推。

    `trace_backend`：`langfuse`（本机自托管服务，选它时**启动前先打健康检查探针**，
    服务没起当场报错不进 run）或 `local`（落本地 JSON）；langfuse 不写本地事件副本。
    None = 取 `pokemon_agent.config.TRACE_BACKEND`（系统缺省）；显式传参优先于它。

    **plan 位置的规划来源就是 brain**（0922 第 182 条撤销 `planner` 壳）：
    `plan_run` 格直接调注入的 `planner`（brain 的 plan 链路），没有"人不给目标就没人给"的问题——
    开局目标由 `goals` 参数给，运行中的新目标由模型规划、人经 `reviewer`
    插话表态。

    **两者必须共享同一份策略对象**：`reviewer` 被 `plan`（插话）和 `review`
    （审）两处读，传进来的必须是同一个实例——否则"人对 plan 的那一版说的话"
    传到审那一格就断了，而表现只是"人说了话、图却像没听见"。

    **没有存档 / 恢复参数**（0913 存档链整体删除）：`resume_cursor` 这类
    "从第 N 个事件接着跑"的入口与存档端是**成对的**，恢复链删掉之后它就没有
    消费方了——单独留一个裸游标参数，只会让下一个人以为还能接上。（`save_checkpoint`
    那个占位格已随 0923 压格删除——图拓扑归 `episode_graph.py` 管，与这里
    有没有参数无关。）
    """
    # 步骤 1：读取预算和环境；世界、记忆与大脑经各自 tool 工厂装配。
    budget = load_run_config(config).budget
    assert budget.task_max_steps + 1 <= SCOPE_IMAGE_CAP, (
        f"SCOPE_IMAGE_CAP={SCOPE_IMAGE_CAP} must be >= "
        f"task_max_steps + 1={budget.task_max_steps + 1}"
    )
    deadline = (
        Deadline(budget.wall_clock_s, budget.reserve_s, budget.min_request_s)
        if budget.wall_clock_s is not None
        else None
    )
    load_env_file()

    world_server_url = (world_server_url or env_str("MCP_WORLD_SERVER_URL") or "").strip() or None
    if world_server_url is None:
        raise McpTransportError(
            "world 只经 MCP：设 MCP_WORLD_SERVER_URL 或传 world_server_url，并先起 world server"
        )
    health = assert_mcp_server_ready(world_server_url, "world")
    logger.info(
        "world MCP server 健康检查通过（%s lease_owner=%s）",
        world_server_url,
        health.get("lease_owner"),
    )
    game = WorldMcpTool.build(world_server_url=world_server_url)

    # 一条事件一个 json 文件落盘（0910 重构）；
    # 文件名是时间递增 uuid，**排序看内容里的 `(ts, uuid)`**（0914 封套改造：
    # 原先那个全局单调 `event_id` 已删，见 `trace/store.py` 的模块 docstring）。
    # **不再有内存事件槽**：`event_sink` 双写随 `RunDataCenter` 一起删除，
    # 磁盘账本（`deps.trace.read_events()`）是唯一真相——图内节点直接读它
    # （原来的另一个读者 SSE 端点随 `api.py` 0913 晚一起删了）。
    #
    # trace 后端不在这里造：`TraceTool.build()` 是唯一的接线工厂，选择 local 或 Langfuse；
    # 本装配点只递裸字段。与
    # `BrainTool.build()` / `MemoryTool.build()` / `WorldMcpTool.build()` 同形。
    # **本文件对 `pokemon_agent.trace` 零 import**（探针也经 tool 层的再出口拿）。
    #
    # **Langfuse 是真实 run 的默认后端**（0927 定案）：SDK 是异步批量发送，
    # 服务不在场时写入侧静默丢账——所以选 langfuse 时先打健康检查探针，
    # "服务没起"挡在 run 开始之前，不跑一半才发现。
    trace_backend = trace_backend or TRACE_BACKEND
    if trace_backend == "langfuse":
        langfuse_version = assert_server_ready()
        logger.info("Langfuse 后端健康检查通过（version=%s）", langfuse_version)
    trace_tool = TraceTool.build(
        run_id=run_id,
        # trace_root 仅对 local 后端生效——langfuse 传了会被 TraceTool.build 拒收（335）。
        trace_root=trace_root if trace_backend == "local" else None,
        branch=branch,
        live_feed_url=live_feed_url,
        backend=trace_backend,
    )

    # 步骤 2：记忆只经 MCP 访问，缺地址在装配期失败。
    memory_server_url = (
        memory_server_url or env_str("MCP_MEMORY_SERVER_URL") or ""
    ).strip() or None
    if memory_server_url is None:
        raise McpTransportError(
            "memory 只经 MCP：设 MCP_MEMORY_SERVER_URL 或传 memory_server_url，并先起 memory server"
        )
    health = assert_mcp_server_ready(memory_server_url, "memory")
    logger.info(
        "memory MCP server 健康检查通过（%s service=%s root=%s）",
        memory_server_url,
        health.get("service"),
        health.get("root"),
    )

    memory = MemoryTool.build(memory_root=memory_root, memory_server_url=memory_server_url)

    # **brain 的四个 provider 不在这里造**（2026-09-13，S6）：哪个技能接哪家
    # 厂商、temperature 分几层，都是 brain 那条链路的接线知识，收在
    # `brain/build_llm_providers.py` + `BrainTool.build()`。
    # 本装配点只递**型号名**这几个裸字段（0913 深夜九：此前递的是
    # `BrainLlmConfig`，需要 `from pokemon_agent.brain import BrainLlmConfig`
    # ——一行非 tool 层的 brain import；改成裸字段后本文件对 brain 零 import）。
    #
    # **厂商由型号名前缀决定**（0914 起）：四个位置可以任意混搭，
    # 表在 `brain/providers.py::_PROVIDER_PREFIXES`。前缀不认识时 `provider_for()`
    # 在装配期抛 `ValueError`（不拖到第一次调用才 404）。
    #
    # temperature 分层（0907 实测依据，见 CHANGELOG）：judge/verify/plan 是
    # 判定与结构化输出任务，确定性优先 → 0；decision 保留 0.3 的少量随机
    # （完全归零会让同一局面反复交出同一动作，探索多样性靠它兜底，
    # 死循环另有 stall 检测与 judge 兜底）。这三个值住在
    # `brain/build_llm_providers.py` 的常量里（常量不是旋钮）。
    # 选型的入口收敛到本方法的关键字参数。
    # **按需实例化**（0922 185）：每层一个 BrainTool，只造它要的链路——
    # 层间不共享 Brain/provider，task 层换策略（JEV / 小快模型）只碰自己那份。
    run_brain = BrainTool.build(
        plan=plan_model or "doubao-seed-2-1-pro-260628",
        judge=judge_model,
        max_tokens=max_tokens,
        plan_max_tokens=budget.plan_max_tokens,
        plan_thinking=budget.plan_thinking,
        plan_timeout_s=budget.plan_timeout_s,
        max_attempts=budget.brain_max_attempts,
        deadline=deadline,
    )
    episode_brain = BrainTool.build(
        plan=plan_model or "doubao-seed-2-1-pro-260628",
        judge=judge_model,
        verify=verify_model or "doubao-seed-2-1-pro-260628",
        max_tokens=max_tokens,
        plan_max_tokens=budget.plan_max_tokens,
        plan_thinking=budget.plan_thinking,
        plan_timeout_s=budget.plan_timeout_s,
        max_attempts=budget.brain_max_attempts,
        deadline=deadline,
    )
    task_brain = BrainTool.build(
        text=text_model,
        judge=judge_model,
        verify=verify_model or "doubao-seed-2-1-pro-260628",
        max_tokens=max_tokens,
        plan_max_tokens=budget.plan_max_tokens,
        plan_thinking=budget.plan_thinking,
        plan_timeout_s=budget.plan_timeout_s,
        max_attempts=budget.brain_max_attempts,
        deadline=deadline,
    )

    reviewer = reviewer or NullReviewer()

    # `interaction` 那个"在这里先落实成一个真实例"的步骤已删（0914 控制台改造）：
    # 跨线程信箱整套下线，取而代之的是 `reviewer`/`planner` 两个同步接口——
    # 无头场景由上面 runtime 构造处的 `NullReviewer` 兜底，不存在"两份实例"的风险。

    # **三层 runtime 嵌套成一份 context**：三张图与图外三个入口（`run_entry` /
    # `episode_entry` / `task_entry`）共用它。同一个
    # trace 实例注入两端——episode 写事件、run 级读盘；同一个 reviewer 实例注入
    # `plan`（插话）与 `review`（审）两处——人对 plan 那一版说的话和审时的表态
    # 走的是同一扇门。
    #
    # **`reviewer` 不传就装配成 Null 实现**（0914 控制台改造）：
    # 无头 run 的语义是"LLM 出什么就是什么、没人插话也没人推翻"。
    # plan 位置的规划来源是 brain 本身（0922 第 184 条撤销 `planner` 壳，
    # 185 起注入的就是能力对象）：`plan_run` 格直接调注入的 `planner`。
    # task 层容器先行（第 181 条）；routes 表已随 186 删除——按 kind 选 provider
    # 是拆解器落地后的事，到那天在这里装配（铁律 3：组装只发生在一个地方）。
    #
    # **三张图与存档器**：图只在这里编译；只有 run 图挂 saver，内层两张图的状态经嵌套命名空间
    # 写进同一个库。存档器拿着 run 图与三个 tool，由三层 runtime 共享同一实例；
    # `CHECKPOINT_ENABLED` 关掉时不造它（各入口见 None 即不存档）。库与存档缺省落在
    # 进程启动目录下的 `checkpoints/`（与 `tracelog/`、`memory/` 同一口径）。
    checkpoint_dir = (
        Path(checkpoint_root) if checkpoint_root is not None else Path.cwd() / "checkpoints"
    )
    saver = build_saver(checkpoint_dir)
    task_graph = compile_task_graph()
    episode_graph = compile_episode_graph()
    run_graph = compile_run_graph(checkpointer=saver)
    checkpointer = (
        Checkpointer(
            root=checkpoint_dir,
            run_graph=run_graph,
            game=game,
            memory=memory,
            trace=trace_tool,
            branch=branch,
            models={
                "text": text_model,
                "judge": judge_model,
                "verify": verify_model,
                "plan": plan_model,
            },
        )
        if CHECKPOINT_ENABLED
        else None
    )
    task_rt = TaskRuntime(
        budget=budget,
        deadline=deadline,
        game=game,
        chooser=task_brain.chooser,
        judger=task_brain.judger,
        memory=memory,
        reflector=task_brain.reflector,
        verifier=task_brain.verifier,
        task_summarizer=task_brain.task_summarizer,
        trace=trace_tool,
        checkpointer=checkpointer,
    )
    episode_rt = EpisodeRuntime(
        budget=budget,
        deadline=deadline,
        game=game,
        memory=memory,
        decomposer=episode_brain.decomposer,
        judger=episode_brain.judger,
        verifier=episode_brain.verifier,
        summarizer=episode_brain.summarizer,
        trace=trace_tool,
        reviewer=reviewer,
        task_graph=task_graph,
        task=task_rt,
        checkpointer=checkpointer,
    )
    run_rt = RunRuntime(
        deadline=deadline,
        budget=budget,
        trace=trace_tool,
        memory=memory,
        game=game,
        reviewer=episode_rt.reviewer,
        planner=run_brain.planner,
        run_summarizer=episode_brain.run_summarizer,
        judger=run_brain.judger,
        episode_graph=episode_graph,
        episode=episode_rt,
        checkpointer=checkpointer,
    )
    run_harness = RunHarness(run_rt, run_graph)

    return run_harness, game
