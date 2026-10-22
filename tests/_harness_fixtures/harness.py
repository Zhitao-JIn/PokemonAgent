"""用假大脑 / 假世界 / 假记忆把**真的三张图**跑一遍，交回落盘账本——给 `test_node_io.py` 当样本。

图、harness、`TraceTool` 渲染与落盘都是真的；只有模型、PyBoy、记忆库是假的。
这样核对脚本面对的是**真实形状**的账，而不是手写的近似品：harness 改了发账顺序，
这里立刻跟着变。

三个判定按目标文字分层：task 的目标恒为 `SUBTASK`，run 的目标以"依次完成"开头，
其余是 episode 的目标。每层给一个"第 n 次被问时判不判完成"的函数。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Task
from pokemon_agent.direct.brain_tool import (
    Chooser,
    Decomposer,
    Judger,
    Planner,
    Reflector,
    RunSummarizer,
    Summarizer,
    TaskSummarizer,
    Verifier,
)
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness import EpisodeRuntime, RunHarness, RunRuntime, TaskRuntime
from pokemon_agent.harness.checkpoint import Checkpointer, build_saver
from pokemon_agent.harness.episode import compile_episode_graph
from pokemon_agent.harness.interface.reviewer import Reviewer
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.settings import AppConfig

from .app_config import ACTION_LIMITS, DEFAULT_APP_CONFIG, call_policy
from .brain import _Brain
from .memory import _Memory
from .world import _Game

SUBTASK = "子任务"
"""假拆解给出的每个 task 的目标文字（task 层判定据此认出自己）。"""

_MOCK_DELAY_SECONDS = 0.003
"""每个假件返回前垫的延迟（2026-09-27）。

目的有二：让 rehearsal/测试里的账本带上**非零的真实形状**——模型账的
payload 双时刻（真 `brain.py` 在 provider 前后取时，假件在这里同形盖戳，
练的是 `render._payload_time` 提取路径）与检索 req 的计时字段不再是 0；
也让 UI 时间线上相邻的账拉开一点间隔。
"""

Policy = Callable[[int], bool]
"""第 n 次（从 1 起）被问"完成了没有"时的回答。"""


def every(n: int) -> Policy:
    """第 n、2n、3n… 次被问时判完成。"""
    return lambda asked: asked % n == 0


EVERY_OTHER: Policy = every(2)
"""缺省：每层第 2、4、6… 次被问时判完成。"""


def never(asked: int) -> bool:
    """永远判没完成（task 只能靠机械预算收场）。"""
    return False


@dataclass
class FakeRun:
    """一套装配好的假 run：真的三张图 + 假大脑 / 假世界 / 假记忆，外加（可选的）存档器。"""

    harness: RunHarness
    run_rt: RunRuntime
    trace: TraceTool
    game: _Game
    memory: _Memory
    checkpointer: Checkpointer | None


GOAL = Task(task_id="g1", goal="到达A", success_criteria="在A", max_steps=3)
"""假 run 的唯一目标。"""


def build_fake(
    tmp_path: Path,
    *,
    run_id: str = "r1",
    task: Policy = EVERY_OTHER,
    episode: Policy = EVERY_OTHER,
    run: Policy = EVERY_OTHER,
    tasks_per_plan: int = 2,
    fail_on_press: int | None = None,
    fail_on_decompose: int | None = None,
    reviewer: Reviewer | None = None,
    checkpoints: bool = False,
    branch: str = "main",
    backend: str = "local",
    config: AppConfig = DEFAULT_APP_CONFIG,
) -> FakeRun:
    """装配一套假 run（`build.py` 的假件版）。`checkpoints=True` 时挂 sqlite saver 与存档器，
    库与存档都放在 `tmp_path/checkpoints/`；`branch` 给恢复出来的执行线用。
    `backend` 透传给 `TraceTool.build`（`"langfuse"` = 写本机 Langfuse，不落本地账）。
    """
    brain = _Brain(task, episode, run, tasks_per_plan, fail_on_decompose)
    memory, game = _Memory(tmp_path / "memory_snapshots"), _Game(fail_on_press)
    trace = TraceTool.build(
        run_id=run_id,
        **({} if backend != "local" else {"trace_root": str(tmp_path / "trace")}),
        branch=branch,
        backend=backend,
    )
    reviewer = reviewer or NullReviewer()
    saver = build_saver(tmp_path / "checkpoints") if checkpoints else None
    task_graph, episode_graph = compile_task_graph(), compile_episode_graph()
    run_graph = compile_run_graph(checkpointer=saver)
    checkpointer = (
        Checkpointer(
            root=tmp_path / "checkpoints",
            run_graph=run_graph,
            game=game,
            memory=memory,
            trace=trace,
            branch=branch,
        )
        if saver is not None
        else None
    )
    run_rt = assemble_runtime(
        brain, game, memory, trace, reviewer, checkpointer, task_graph, episode_graph, config
    )
    return FakeRun(RunHarness(run_rt, run_graph), run_rt, trace, game, memory, checkpointer)


def assemble_runtime(
    brain: _Brain,
    game: _Game,
    memory: _Memory,
    trace: TraceTool,
    reviewer: Reviewer,
    checkpointer: Checkpointer | None,
    task_graph: CompiledStateGraph,
    episode_graph: CompiledStateGraph,
    config: AppConfig = DEFAULT_APP_CONFIG,
) -> RunRuntime:
    prompt_gateway = PromptGateway(None)
    """共享同一套依赖装配三层 runtime；图与依赖由调用方注入。"""
    task_rt = TaskRuntime(
        config=config,
        game=game,
        chooser=Chooser(
            brain, policy=call_policy(), action_limits=ACTION_LIMITS, prompt_gateway=prompt_gateway
        ),
        judger=Judger(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        memory=memory,
        reflector=Reflector(brain),
        verifier=Verifier(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        task_summarizer=TaskSummarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        trace=trace,
        reviewer=reviewer,
        checkpointer=checkpointer,
    )
    episode_rt = EpisodeRuntime(
        config=config,
        game=game,
        memory=memory,
        decomposer=Decomposer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        judger=Judger(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        verifier=Verifier(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        summarizer=Summarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        trace=trace,
        reviewer=reviewer,
        task_graph=task_graph,
        task=task_rt,
        checkpointer=checkpointer,
    )
    return RunRuntime(
        config=config,
        trace=trace,
        memory=memory,
        game=game,
        reviewer=reviewer,
        planner=Planner(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        run_summarizer=RunSummarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        judger=Judger(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        episode_graph=episode_graph,
        episode=episode_rt,
        checkpointer=checkpointer,
    )


def run_fake(tmp_path: Path, **kwargs: object) -> list[dict]:
    """跑一个 run，返回落盘账本（`load_events()` 同形：`meta`/`content` 是 JSON 字符串）。

    参数同 `build_fake`。`fail_on_press`：第 n 次按键时世界抛 `AgentError`（task 级异常，
    episode 的 `act` 接住）；`fail_on_decompose`：第 n 次拆解时抛 `AgentError`（episode 级异常，
    run 的 `act` 接住）。
    """
    run_id = str(kwargs.get("run_id", "r1"))
    fake = build_fake(tmp_path, **kwargs)  # type: ignore[arg-type]
    fake.harness.run(run_id, [GOAL])
    return [json.loads(e.model_dump_json()) for e in fake.trace.read_events({"run_id": run_id})]
