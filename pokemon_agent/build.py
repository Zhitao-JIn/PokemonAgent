"""全项目唯一装配点：把所有具体实现 new 起来，拼成 RunHarness 与 WorldMcpTool。

**`build_real` 不收任何显式参数，只收配置文件路径**：全部取值来自 `settings/default.json`
（保底）+ 启动时指定的覆盖文件；密钥（API key、`LANGFUSE_*`）仍只走 `.env`/环境变量，
不进 JSON。想知道某个值在哪改，只看配置文件，不用翻调用方。

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
from collections.abc import Sequence
from pathlib import Path

from pokemon_agent.deadline import Deadline
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.direct.reviewer_tool import ReviewerTool
from pokemon_agent.direct.trace import TraceTool, assert_server_ready
from pokemon_agent.env import load_env_file
from pokemon_agent.harness import EpisodeRuntime, RunHarness, RunRuntime, TaskRuntime
from pokemon_agent.harness.checkpoint import Checkpointer, build_saver
from pokemon_agent.harness.episode import compile_episode_graph
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.mcpclient import assert_mcp_server_ready
from pokemon_agent.mcpclient.client import McpTransportError
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.settings import load_config, resolve_path, write_snapshot

logger = logging.getLogger(__name__)


def build_real(
    config: str | Path | Sequence[str | Path] | None = None,
) -> tuple[RunHarness, WorldMcpTool]:
    """装配真实链路；返回 `(harness, game)`。

    `config`：覆盖文件路径（单个或按顺序多个，后者胜）；`None` 只用保底 `default.json`。
    这是唯一的入参——型号、路径、服务地址、预算、复核模式全部来自配置文件。

    - world / memory 只经 MCP：`services.world_server_url` / `services.memory_server_url`
      缺省为 `null`，装配期抛 `McpTransportError`；有地址先探 `/health`。
    - `trace.backend = "langfuse"` 时先探 Langfuse 健康检查，服务没起当场报错不进 run。
    - `review.mode` 为 `off` 时无头（`NullReviewer`），其余经 `ReviewerTool.build` 接独立
      reviewer 进程；reviewer 进程另行启动、读同一份配置。
    - 生效配置（含来源与 sha256）落一份快照到 `paths.config_snapshot`，供事后核对"这次 run
      到底用了什么值"。

    **事件流不在返回值里**：harness 侧全部读点走 `Runtime.trace`；外部要读账一律经
    `deps.trace`。
    """
    # 步骤 1：加载生效配置并落快照；密钥只从 `.env` / 环境变量读。
    resolved = load_config(config)
    app = resolved.config
    load_env_file()
    snapshot = write_snapshot(resolved, resolve_path(app.paths, "config_snapshot"), app.run.run_id)
    logger.info("生效配置 sha256=%s 快照=%s", resolved.sha256[:8], snapshot)

    budget = app.budget
    deadline = (
        Deadline(budget.wall_clock_s, budget.reserve_s, budget.min_request_s)
        if budget.wall_clock_s is not None
        else None
    )

    # 步骤 2：世界、trace、记忆经各自 tool 工厂装配。
    world_url = app.services.world_server_url
    if world_url is None:
        raise McpTransportError(
            "world 只经 MCP：在配置里设 services.world_server_url 并先起 world server"
        )
    health = assert_mcp_server_ready(world_url, "world")
    logger.info(
        "world MCP server 健康检查通过（%s lease_owner=%s）", world_url, health.get("lease_owner")
    )
    game = WorldMcpTool.build(world_server_url=world_url)

    backend = app.trace.backend
    if backend == "langfuse":
        logger.info("Langfuse 后端健康检查通过（version=%s）", assert_server_ready())
    trace_tool = TraceTool.build(
        run_id=app.run.run_id,
        trace_root=resolve_path(app.paths, "trace") if backend == "local" else None,
        branch=app.run.branch,
        backend=backend,
    )

    memory_url = app.services.memory_server_url
    if memory_url is None:
        raise McpTransportError(
            "memory 只经 MCP：在配置里设 services.memory_server_url 并先起 memory server"
        )
    health = assert_mcp_server_ready(memory_url, "memory")
    logger.info(
        "memory MCP server 健康检查通过（%s service=%s root=%s）",
        memory_url,
        health.get("service"),
        health.get("root"),
    )
    memory = MemoryTool.build(
        memory_server_url=memory_url, memory_root=resolve_path(app.paths, "memory")
    )

    # 步骤 3：按层各造一份 brain，只装本层要的链路；型号与超参全取自 `models`。
    def brain(*links: str) -> BrainTool:
        return BrainTool.build(
            links=links,
            models=app.models,
            prompt_registry=app.prompt.registry,
            retry=app.retry,
            request_timeouts=app.request_timeouts_s,
            action_limits=app.action_limits,
            image_cap=app.memory.scope_image_cap,
            vision_dump_dir=app.debug.vision_dump_dir,
            deadline=deadline,
        )

    run_brain = brain("plan", "judge")
    episode_brain = brain("plan", "judge", "verify")
    task_brain = brain("text", "judge", "verify")

    reviewer = ReviewerTool.build(app.review, flush=trace_tool.flush)

    # 步骤 4：编译三张图与存档器；只有 run 图挂 saver。
    checkpoint_dir = resolve_path(app.paths, "checkpoint")
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
            branch=app.run.branch,
            models={
                "text": app.models.text.model,
                "judge": app.models.judge.model,
                "verify": app.models.verify.model,
                "plan": app.models.plan.model,
            },
        )
        if app.checkpoint.enabled
        else None
    )

    # 步骤 5：三层 runtime 嵌套成一份 context；trace / memory / reviewer / game 三层同一实例。
    task_rt = TaskRuntime(
        config=app,
        deadline=deadline,
        game=game,
        chooser=task_brain.chooser,
        judger=task_brain.judger,
        memory=memory,
        reflector=task_brain.reflector,
        verifier=task_brain.verifier,
        task_summarizer=task_brain.task_summarizer,
        trace=trace_tool,
        reviewer=reviewer,
        checkpointer=checkpointer,
    )
    episode_rt = EpisodeRuntime(
        config=app,
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
        config=app,
        deadline=deadline,
        trace=trace_tool,
        memory=memory,
        game=game,
        reviewer=reviewer,
        planner=run_brain.planner,
        run_summarizer=episode_brain.run_summarizer,
        judger=run_brain.judger,
        episode_graph=episode_graph,
        episode=episode_rt,
        checkpointer=checkpointer,
    )
    return RunHarness(run_rt, run_graph), game
