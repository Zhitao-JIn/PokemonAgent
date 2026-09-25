"""run 图的**图外侧门**：一个 run 的开局（`new_run`）。

和图内节点的分工，跟 `episode/episode_entry.py` 与它那些节点的分工是同一个意思：
**凡是"在进图之前必须先做完、且做完才有一个完整初值"的事，都住图外**。run 侧这件是

- `new_run`：造初始 `RunState` → 载世界起点（`game.reset`，每 run 一次）
  → 进图 → 取结算（异常路径补 `RUN_ERROR`）。

**起止账都在图内**：`run_start` 在 `begin`、`run_end` 在 `run_done`。本入口只记它亲手
接住的 `RUN_ERROR`，再原样抛，**不吞**（谁接住谁记账：episode 的异常由 run 的 `act`
记 `episode_error`，task 的异常由 episode 的 `act` 记 `task_error`）。

**存档/恢复已整体删除**（见 `CHANGELOG.md` 2026-09-13 第 57 条）：原先这里有第二个
入口 `resume_run`（读存档锚点 → 重建 `RunState` → 进图 → 补 `CHECKPOINT_RESTORE`
→ 取结算），随 `EpisodeCheckpoint` 一起删掉了。

**`recursion_limit` 的常量住顶层 config**（`RUN_RECURSION_LIMIT`）：`invoke_run()` 是它唯一
的读者，它是 run 级的**闸门**而不是预算——贴身的限在内层
task 层的贴身限（`task_entry.task_budget`，按键数算），三层的分工见那个常量
自己的 docstring。

**函数名与 `episode_entry` 刻意不同**：那边是 `run_episode`（"跑一局"），
这里是 `new_run`（"起一个 run"），两个入口名 grep 时不撞。

**`goals` 进、`plan` 表的构造在这里**（0914 控制台改造）：调用方递的还是
一个 `list[Task]`（实验层与核对脚本的口径不变——它们不该知道 `GoalEntry`），
本函数把它包成初始目标表（全部 `PENDING`、`attempts=0`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Goal, Task
from pokemon_agent.config import RUN_RECURSION_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolResetReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeOutput, GoalEntry

from .run_done import settle_run
from .run_state import RunState
from .runtime import RunRuntime


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——run_error 的 req 的 error 字段只吃文本，
    Exception 对象进不了 Pydantic req。

    与 `episode_entry.exc_snapshot` 同形：两个模块各写各的（各自只有一个读者，
    都在自己的 `try` 里），不为省三行跨层 import 一个"共用件"。
    """
    return f"{type(exc).__name__}: {exc}"


def initial_plan(goals: list[Task]) -> list[GoalEntry]:
    """把调用方给的 `list[Task]` 包成初始目标表（全 `PENDING`、零尝试）。

    后置条件：返回条数与 `goals` 相等，顺序照原序（表序 = 派发顺序）。
    """
    return [GoalEntry(task=task, status=EntryStatus.PENDING) for task in goals]


def default_run_goal(goals: list[Task]) -> Goal:
    """调用方没给 `run_goal` 时，用初始目标表的文字拼一个（依次完成表上全部目标）。"""
    return Goal(
        goal="依次完成：" + "；".join(task.goal for task in goals),
        criteria="；".join(task.success_criteria for task in goals),
    )


def new_run(
    deps: RunRuntime,
    graph: CompiledStateGraph,
    *,
    run_id: str,
    goals: list[Task],
    run_goal: Goal | None = None,
) -> tuple[list[EpisodeOutput], int, int, float]:
    """跑完一个 run：载入世界起点，然后目标表逐个解决（每条一个 episode），返回 run 级结算。

    返回 `(outcomes, total, succeeded, success_rate)` 四个裸值，不打包成对象——
    trace 里那条 RUN_END 内嵌的 `RunResp` 由图内 `run_done` 组装。

    **世界起点载入（`game.reset`）在本函数内、进图之前**：每 run 恰好一次，失败
    视为 run 级失败（异常穿 `except` 补 RUN_ERROR 后原样抛）。

    `goals` 是初始目标表，按表序逐条派发（`dispatch` 取**第一条 `PENDING`**）；
    每轮 `plan` 读历史决定要不要拆新目标。**失败的目标由 `review` 盖成 `FAILED`
    （终态，不自动重派）**——要再跑一局得由 `plan` 里 brain 的下一版规划显式把它
    重开成 `PENDING`（"重试是 plan 的决策，不是自动动作"）。结算累积在 `episode_outputs`，
    这里组装汇总。

    后置条件：正常路径 trace 里恰好多一条 RUN_START（`begin`）和一条 RUN_END（`run_done`）；
    异常路径补一条 RUN_ERROR 后原样抛出，不吞。
    """
    assert run_id, "new_run() got an empty run_id"
    assert goals, "new_run() got an empty goal table"

    goal = run_goal or default_run_goal(goals)

    state = RunState(
        run_id=run_id,
        run_goal=goal,
        goals=initial_plan(goals),
    )
    # `run_id` 的真源在 `state.run_id`（186 起 id 归 state，runtime 不再复制）；
    # trace 事件的归属章由 `TraceTool.build(run_id=…)` 在构造期持有，与这里同值。
    try:
        # 世界起点只在 run 开始时载一次（`load_state` 回 ROM 起点存档）；之后的每个
        # episode **不重置**，接着上一局结束的状态继续跑——跨局累积进度全靠这一点
        # （取舍见 `CHANGELOG.md` 2026-09-03 条目）。reset 住在这里（图外、"每 run
        # 恰好执行一次"的位置），"只做一次"由代码位置保证——不再需要
        # `world_reset_done` 那个跨局记号（2026-09-22 第 178 条删除）。
        # task 取表序第一条（run 从第一个目标开局）；world 只拿它做断言与
        # "将来按任务选起始存档"，真正的任务编排仍由 `dispatch` 逐局决定。
        # `game` 住在 `EpisodeRuntime` 上（episode 独占），run 侧经嵌套穿透。
        deps.episode.game.reset(FromHarnessToGameToolResetReq(task=goals[0]))
        if deps.checkpointer is not None:
            deps.checkpointer.save(level="run", state=state)
        final = invoke_run(deps, graph, state, thread=thread_id(run_id, state.branch))
    except Exception as exc:
        # 异常路径：谁接住谁记账——这里接住的是整个 run 的异常，记 RUN_ERROR 再原样抛出，不吞。
        record_run_error(deps, run_id, exc, source="run_entry.new_run")
        raise
    return close(final)


def record_run_error(deps: RunRuntime, run_id: str, exc: Exception, *, source: str) -> None:
    """记一条 `run_error`（整个 run 的异常快照），再把半截那一局已写出的账封存（有存档器时）。

    source：接住异常的位置——`"run_entry.new_run"`，或恢复路径 `"checkpoint.restore"`。
    """
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_ERROR,
            meta={"source": source, "episode_id": run_id, "task_id": run_id, "step": 0},
            error=exc_snapshot(exc),
        )
    )
    if deps.checkpointer is not None:
        deps.checkpointer.seal_episode(run_id=run_id, step=0)


def close(final: dict[str, Any]) -> tuple[list[EpisodeOutput], int, int, float]:
    """收尾：从终态拆出四个裸值（结算与 `run_end` 账已由图内 `run_done` 做完）。"""
    result = settle_run(RunState.model_validate(final))
    return result.outcomes, result.total, result.succeeded, result.success_rate


def invoke_run(
    deps: RunRuntime, graph: CompiledStateGraph, state: RunState | None, *, thread: str
) -> dict[str, Any]:
    """进图：递 `RUN_RECURSION_LIMIT`（闸门）与 `deps`（唯一的 context）。

    state：初始状态；恢复路径传 None——从 thread 上已写好的那一条接着跑（`update_state` 之后）。

    **`context=deps` 是必需项**（D3/F10）：run 图的节点也是自由函数，依赖只从
    `runtime.context` 来；不给会让 `plan`/`dispatch`/`review` 读到一份空的 context
    ——炸在第一个读依赖的节点上。

    **thread 与落库时机**：`thread_id = <run_id>@<branch>`，一条执行线一个 thread。有 saver 时
    `durability="sync"`——每格的 checkpoint 写完才进下一格，存档时查外层"进 act 前"那一条才可靠；
    episode / task 两层的 `invoke` 从 config 继承这个设置。无 saver 时不传：langgraph 1.2.11
    在无 saver 时收到 `"sync"` 会抛 `AttributeError`。
    """
    return graph.invoke(
        state,
        {"recursion_limit": RUN_RECURSION_LIMIT, "configurable": {"thread_id": thread}},
        context=deps,
        durability="sync" if graph.checkpointer is not None else None,
    )


def thread_id(run_id: str, branch: str) -> str:
    """LangGraph thread 的名字：一条执行线一个 thread（`docs/checkpoint/spec.md` §5.4）。"""
    assert run_id and branch, "thread_id() needs both run_id and branch"
    return f"{run_id}@{branch}"


__all__ = [
    "RUN_RECURSION_LIMIT",
    "close",
    "default_run_goal",
    "exc_snapshot",
    "initial_plan",
    "invoke_run",
    "new_run",
    "record_run_error",
    "thread_id",
]
