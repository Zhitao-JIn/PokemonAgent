"""`dispatch`：**纯前置**——选中下一条待派目标、盖 `RUNNING`、备好这一局的标识与初值；
派发本身归 `episode` 那格。

它准备五样（这就是 D2 那张父子交界键表的**写入侧**）：

- **选目标**：目标表里**第一条 `PENDING`**（表序，不是表末——旧栈的 LIFO 语义已废）；
- **盖状态**：那一条 `PENDING → RUNNING`（机械，见 `GoalStatus` 的权限表）；
- `episode_id`（`{run_id}-ep{序号}`，run 内唯一）；
- `task` = 选中那一层的任务，`episode_goals` = **这一局的目标栈**
  （活跃条目投影，**正在跑的那条排在最后**——子图把最后一位当"你现在要完成的"，
  见 `active_stack()`）；
- `attempts += 1`（**只加到选中那条上**，不再是"最后一个元素 +1"）。

`episode_goals` 用活跃条目（`PENDING`/`RUNNING`）投影：`COMPLETED`/`FAILED`/
`ABANDONED` 的条目已经从"还要做什么"里出局，留在投影里只会给大脑看一堆已完成的
噪音；但它们**留在 `plan` 表里**（层次上下文与教训）。**顺序由 `active_stack()`
定：正在跑的那条排最后**——这条不是排版偏好，是子图读法（`[-1]` = 当前目标）
的硬要求，写错的后果见 `active_stack()` 的 docstring。

不在这里捕获 `AgentError`——那件事归本文件里的 `episode_error_handler`（F4）。
**handler 的 goto 已改为 `"review"`**：`reflect` 节点整个删掉了，收结算与盖章
现在都是 `review` 的活。

**为什么 handler 住这个文件**（它服务的其实是 `episode` 那一格）：它是原先
`dispatch` 里那句 `except AgentError` 的直系后代，PLAN §3.1 把两者放在一起，
"派发这一局"的**前置 + 兜底**合成一个文件；`add_node("episode", …, error_handler=…)`
那行绑定读起来也仍然是一处（`run_graph.py`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command

from pokemon_agent.brain import Goal
from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp
from pokemon_agent.schemas.harness.domain import GoalEntry, GoalStatus

from ...deps import HarnessDeps
from ..run_state import RunState


def active_stack(plan: list[GoalEntry], task_id: str) -> list[GoalEntry]:
    """这一局的**目标栈**：活跃条目，**正在跑的那条排在最后**。

    **为什么不是"照表序"**：子图把列表的**最后一位**当成"你现在要完成的"——
    `judge` 判 `goals[-1]`，
    `decide_action._render_goals()` 给最后一位标 `← 你现在要完成的`。
    而 `dispatch` 取的是**第一条 `PENDING`**（表序），所以"照表序"只有在活跃条目
    恰好一条时才碰巧等于"当前那条在最后"。表里一旦出现**同层兄弟**（`Planner`
    一次推 ≥2 条就会），照表序投影会让子图**拿着兄弟 A 去判兄弟 B 的达成情况**。

    0914 的改造漏了这一步，而且漏得不只是判错目标：`episode()` 那格还在读
    已经被拆掉的 `state.goals`，于是**图根本跑不起来**（真机一撞就
    `AttributeError`）。修法与账见 `CHANGELOG.md` 2026-09-14 第 85 条。

    "活跃"的判据是 `GoalStatus.is_active`（`PENDING`/`RUNNING`）——定义在状态上，
    不散在节点里。终态条目留在 `plan` 表里当上下文与教训，但不进这一份投影。

    前置条件：`task_id` 在活跃条目里**恰好命中一条**（`dispatch` 刚把它盖成
        `RUNNING`，而"至多一条 `RUNNING`"是目标表的不变式）。
    后置条件：返回条数 = 活跃条目数；**末条的 `task_id` == 入参 `task_id`**。
    """
    active = [entry for entry in plan if entry.status.is_active]
    current = [entry for entry in active if entry.task.task_id == task_id]
    assert len(current) == 1, (
        f"目标表里属于 {task_id!r} 的活跃条目应恰好一条，实为 {len(current)} 条"
        "——'至多一条 RUNNING' 这条不变式被破坏了"
    )
    return [entry for entry in active if entry.task.task_id != task_id] + current


def project_goals(plan: list[GoalEntry], task_id: str) -> list[Goal]:
    """`active_stack()` 的 `Goal` 形态——run 侧 `episode_goals` 的取值。

    `plan`（`list[GoalEntry]`）是**"目标表"这个领域概念**，父侧不动；
    `episode_goals`（`list[Goal]`）是**同一次派发算出来的投影视图**——
    两者是不同的东西，所以是两个键（同名不同型会在父子交界当场 `ValidationError`）。

    后置条件：`[-1].goal` == 正在跑那条的 `goal`（子图"判只判栈顶"的前提）。
    """
    return [
        Goal(goal=entry.task.goal, criteria=entry.task.success_criteria)
        for entry in active_stack(plan, task_id)
    ]


def dispatch(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """选中第一条 `PENDING`、盖 `RUNNING`，备好这一局的 `episode_id` / `task` / 投影。

    前置条件：表里至少有一条 `PENDING`（路由已保证——`plan` 出口只在"有
        待派目标"时来这里）。
    后置条件：返回后表里**恰好一条 `RUNNING`**，且它就是 `state.task`。
    """
    index = next(
        (i for i, entry in enumerate(state.plan) if entry.status is GoalStatus.PENDING),
        None,
    )
    assert index is not None, "dispatch() called with no PENDING goal (route should prevent this)"
    selected = state.plan[index].model_copy(
        update={"status": GoalStatus.RUNNING, "attempts": state.plan[index].attempts + 1}
    )
    plan = state.plan[:index] + [selected] + state.plan[index + 1 :]
    episode_id = f"{state.run_id}-ep{len(state.outcomes) + 1}"

    return {
        "episode_id": episode_id,
        "task": selected.task,
        "plan": plan,
        "episode_goals": project_goals(plan, selected.task.task_id),
    }


def episode_error_handler(state: RunState, error: NodeError) -> Command:
    """**单局异常不崩掉整个 run** 的落点（F4 的 `error_handler`）。

    原先这段逻辑是 `dispatch` 里的 `except AgentError`；内置子图之后"父图调用
    那一格"没了，异常由 LangGraph 交给 handler。实测（F4）：handler 拿到的是
    **父 state**，返回 `Command(goto=…, update=…)` 时流程正常继续；
    只返回 dict 的话图会停在这一格（所以必须用 `Command`）。

    **`goto="review"`**（0914 控制台改造）：`reflect` 已删，所以这一格跳过
    "看结算"直接去 `review`——`review` 会先收结算（本次 update 里那条失败
    outcome）再盖章，正是原先 `reflect` 干的事。

    **只吞 `AgentError`**：那才是"单局失败"这一类预期内的失败（有名字、后面
    replay 要按失败类型归类统计）；别的异常仍然是 bug，原样抛出去——这条守的是
    `except AgentError` 时代的语义，不许趁机扩大吞错范围。

    **handler 拿不到 `runtime`**：langgraph 的 handler 签名只有 `(state, error)`，
    所以这一格是本文件唯一不读 `HarnessDeps` 的——它也不需要（写的是结算，
    不碰任何依赖）。
    """
    exc = error.error
    if not isinstance(exc, AgentError):
        raise exc
    assert state.episode_id, "episode_error_handler() without an episode_id"
    return Command(
        goto="review",
        update={
            "outcome": FromRunHarnessToEpisodeHarnessRunResp(
                episode_id=state.episode_id,
                success=False,
                steps=0,
                reason=f"error: {type(exc).__name__}",
            )
        },
    )


__all__ = ["active_stack", "dispatch", "episode_error_handler", "project_goals"]
