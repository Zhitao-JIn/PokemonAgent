"""episode 图的**图外侧门**：开局的装配器（`PLAN_graph_composition.md` §6 步 2）。

## 为什么装配必须在图外（不是取舍，是逻辑上的先后）

图的入口状态必须是**完整的**（它带着不变式 `observation.step == step`）。要是
把装配变成图的一个节点，"进图的初始状态"就只是一个半初始化的 state，图的第一个
节点得能处理"我是刚装配的还是被别的路径塞进来的"——**图就有了两个入口语义**，
每个下游节点都得接受两种初值。那是把"装配"塞进了"运行"里。

于是 `begin_episode` 是**图入口装配器**，住在这个文件里；
而 `close_episode`（只算账、不推世界）在图内——这个不对称是有意的：现行的
"`act` 是唯一推世界的节点"这条约束比对称性重要。

## 本文件提供两个函数

    begin_episode(deps, …)  -> EpisodeRunState   新跑：EPISODE_START + 世界起点 + 开局视觉感知
    run_new(deps, graph, …) -> Outcome           写账 → 进图 → 取结算（异常路径补 EPISODE_ERROR）

`graph` 显式传参（不藏在某个对象里）：它是 `episode/episode_graph.py` 的模块级
编译产物。**它不是 owner**——`run_new` 才是"这一次派发"的编排者。

## 与父图的交界

`deps` 是全图唯一的 context（F10/F11）。本文件读它的 `game` / `trace` /
`memory` / `run_id` / `world_reset_done` / 两张帧表。

**存档/恢复已整体删除（见 `CHANGELOG.md` 2026-09-13 第 57 条）**：原先这里还有
`prepare_resume` / `void_timeline` 与 `run_resume` 三个函数（恢复七步装配 +
废弃时间线归档 + 恢复入口），随 `EpisodeCheckpoint` 一起删掉了。本仓现在只有
"新开一 run"一条路径。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Goal, Task
from pokemon_agent.config import NODES_PER_DECISION, NODES_PER_PRESS, RECURSION_MARGIN
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolResetReq,
    FromHarnessToTraceToolAppendReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    TraceKind,
)

from ..deps import HarnessDeps
from .episode_state import EpisodeRunState
from .press.perceive_after_action import perceive_once


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——`episode_error` 的 req 的 `error` 字段只吃文本，
    `Exception` 对象进不了 Pydantic req（`run/run_entry.py` 里有一份同形的）。
    """
    return f"{type(exc).__name__}: {exc}"


# ---- 装配器（图外）：两条入口的"进图初值" ----


def begin_episode(
    deps: HarnessDeps,
    episode_id: str,
    task: Task,
    stack: list[Task],
) -> EpisodeRunState:
    """开一局：写 EPISODE_START、reset 世界、感知第一帧，返回初始状态。

    `stack` 是整个目标栈（run 级投影）：`episode_goals` = 全栈投影，**判只判栈顶**
    （`episode_goals[-1]` = task.goal），其余层是给大脑的全局信息。
    """
    # 步骤 1：开局账——EPISODE_START。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_START,
            step=0,
            episode_id=episode_id,
            task=task,
        )
    )

    # 步骤 2：世界起点只在 run 的第一个 episode 读一次；后续 episode
    # **不重置**，接着上一局结束的状态继续跑（取舍见 `CHANGELOG.md`
    # 2026-09-03 条目）。局起点不再另存快照——终止判定全在 `judge`
    # 出口；ep1 起点 = `reset()` 加载的 ROM 存档，可复现。
    #
    # 这个记号从 `EpisodeHarness._world_reset_done` 搬到 deps（D11）：它的语义
    # 本来就是 run 级的（"这个 run 的世界起点读过了没有"），跟"哪一局"无关。
    if not deps.world_reset_done:
        deps.game.reset(FromHarnessToGameToolResetReq(task=task))
        deps.world_reset_done = True

    # 步骤 3：感知第一帧（重试循环与记账都在 `press/perceive_after_action.py` 的
    # `perceive_once`——图内那一格用的是**同一个宿主**，所以"这一帧的账"只有一处实现，
    # 步 3 之前这里与 `EpisodeHarness._perceive` 各有一份**同样 8 行**的重复）；
    # 原始画面不随感知调用落盘，而是先暂存进 `deps.pending_frames`——这一帧是第 0 步的
    # 开局画面，等链首的 `record_observation` 记 `OBSERVE` 时，由它把图挂上去并登记登记表。
    obs, frame_png = perceive_once(deps, episode_id, 0)
    if frame_png is not None:
        deps.pending_frames[(episode_id, 0)] = frame_png
    assert not obs.done, "reset() must return a fresh observation"

    # 步骤 4：组装初始状态。**开局这一帧直接就是 `observation`**（第 0 步）：
    # 开局没有"上一步"，不需要 `pending_observation` 那道接力——扶正它是
    # 本函数的活（之后每一步的扶正归 `close_step`）。
    return EpisodeRunState(
        episode_id=episode_id,
        task=task,
        episode_goals=[Goal(goal=t.goal, criteria=t.success_criteria) for t in stack],
        observation=obs,
    )


# ---- 入口：装配 → 进图 → 取结算 ----


def run_new(
    deps: HarnessDeps,
    graph: CompiledStateGraph,
    *,
    episode_id: str,
    task: Task,
    stack: list[Task],
) -> FromRunHarnessToEpisodeHarnessRunResp:
    """跑完一局：解决栈顶这一个目标。

    前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
    后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。

    `stack` 是整个目标栈（全局信息）——投影成 `episode_goals`（判只判栈顶，
    `episode_goals[-1]` = task.goal），其余层是给大脑的全局视野。
    """
    assert episode_id, "run_new() got an empty episode_id"
    assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"
    assert stack and stack[-1].task_id == task.task_id, (
        "run_new() needs a non-empty stack whose top is the task being run"
    )

    # 步骤 1：开局，跑图直到终止。
    # `recursion_limit` 的换算在 `_invoke()` 里（`episode/episode_graph.py` 的
    # `NODES_PER_DECISION` + `NODES_PER_PRESS` 两个常量）——**那两个数字必须跟着
    # `episode/episode_graph.py` 的节点集合一起改**，否则会在步数没走完时被 LangGraph 的
    # `GraphRecursionError` 无声打断（论证见 `CHANGELOG.md` 2026-09-05 条目）。
    try:
        state = begin_episode(deps, episode_id, task, stack)
        final = _invoke(deps, graph, state, task)
    except Exception as exc:
        # 步骤 2：异常路径——补 EPISODE_END（error 变体）再原样抛出。
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_ERROR,
                episode_id=episode_id,
                step=0,
                error=exc_snapshot(exc),
            )
        )
        raise

    return close(final, task)


# ---- 进图与取结算 ----


def _invoke(
    deps: HarnessDeps,
    graph: CompiledStateGraph,
    state: EpisodeRunState,
    task: Task,
) -> dict[str, Any]:
    """跑图直到终止。`recursion_limit` 按剩余步数换算（新跑/恢复同一条公式）。

    **`max_steps` 是"小 action 数"**（每按一个键一步），而一圈的节点数取决于
    这一圈的链长：`NODES_PER_DECISION + NODES_PER_PRESS` 是"链长 = 1"时的
    开销，也正是每步开销的上界（链长 K ≥ 1 时 `10 + 7K ≤ 17K`）。按上界算，
    链再长也不会被 LangGraph 的 `GraphRecursionError` 无声打断。
    **这两个常量必须跟着 `episode/episode_graph.py` 的节点集合一起改**（论证见
    `CHANGELOG.md` 2026-09-05 条目）。

    这一局自己的 limit 是**贴身的那一道**：管"这一局别跑飞"。run 级另有**一个
    闸门常量**（`pokemon_agent/config.py` 的 `RUN_RECURSION_LIMIT`，一个大数、
    不按公式算）——它
    **不覆盖**本局的步数（本仓是形态 B：父子各算各的计数器，实测见探针 X5），
    只负责"整个 run 别无限跑"。

    **`context=deps`（步 3 起是必需项，不是可选项）**：节点从方法搬成自由函数后
    签名是 `(state, runtime: Runtime[HarnessDeps])`，而 `runtime.context` 正是
    这里递进去的那个对象（F6 实测：官方依赖注入通道；F11：框架**不重建**它）。
    此前节点是 `self.xxx` 方法、依赖走 `self.deps`，所以这一步加不加都跑得动；
    搬完第一个节点起，不给就会让节点读到一份空的 context——**炸在第一个节点上**，
    定位成本很低，但别拖到那时才发现。
    """
    return graph.invoke(
        state,
        {"recursion_limit": episode_budget(task, state.step)},
        context=deps,
    )


def episode_budget(task: Task, step: int) -> int:
    """一局从第 `step` 步起还能烧掉多少个 superstep——**这是贴身的那个限**。

    它是"这一局能不能跑完"的守护，逐局按剩余步数算（`judge` 就是按
    `state.step >= task.max_steps` 判停的）。**run 级不再引用它**：那边只留一个可调的
    闸门常量 `run_entry.RUN_RECURSION_LIMIT`（X5 拍板——形态 B 下父子计数独立，
    run 级没有可算的预算；见 `run/run_entry.py` 那个常量的 docstring）。

    上界推导：每按一个键一圈 `NODES_PER_DECISION + NODES_PER_PRESS` 个节点，
    是"链长 = 1"的开销、也是每步开销的上界（链长 K ≥ 1 时 `10 + 7K ≤ 17K`）。
    """
    per_press = NODES_PER_DECISION + NODES_PER_PRESS
    return (task.max_steps - step) * per_press + RECURSION_MARGIN


def close(
    final: dict[str, Any], task: Task
) -> FromRunHarnessToEpisodeHarnessRunResp:
    """收尾：取出图内 `close_episode` 已经写好并落账的结算。

    **图跑完之后这里不再算任何东西**（D2-④）：结算由 `close_episode` 节点
    从同一份 final_state 派生、写进 `state.outcome` 并落 `EPISODE_END`，
    本函数只把它取出来交给调用方。

    顺带在这里落**D6 的事后断言**：一局的步数不可能超过 `task.max_steps`
    （`judge` 就是按 `state.step >= task.max_steps` 判停的）。把"靠 limit 兜底"
    换成"靠断言报警"——真撞上 recursion_limit 是**无声截断**，而这条会在开发期
    就地炸（`PLAN_graph_composition.md` §4 D6）。
    """
    final_state = EpisodeRunState.model_validate(final)
    assert final_state.outcome is not None, "close_episode must have written the outcome"
    assert final_state.outcome.steps <= task.max_steps, (
        f"episode ran {final_state.outcome.steps} steps > max_steps={task.max_steps}"
        " —— 递归上限或终止判定有一个失灵了"
    )
    return final_state.outcome


__all__ = [
    "begin_episode",
    "close",
    "episode_budget",
    "exc_snapshot",
    "run_new",
]
