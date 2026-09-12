"""`dispatch`：**纯前置**——备好这一局的标识与初值，派发本身归 `episode` 那格。

它准备四样（这就是 D2 那张父子交界键表的**写入侧**）：

- `episode_id`（`{run_id}-ep{序号}`，run 内唯一）；
- `task` = 栈顶那一层，`episode_goals` = **整个目标栈的投影**（子图判只判栈顶
  `episode_goals[-1]`，其余层是给大脑的全局视野）。父侧的 `goals` 是"目标栈"这个
  领域概念，不动——两者是不同的东西，所以是两个键；
- `attempts[-1] + 1`：栈顶派发计数；
- `deps.run_state_snapshot`：这一局存档要搭车带的 run 级状态（D11-(3)）。**每局都刷新**，
  多局时每一局的存档携带的都是**那一局派发时**的 run state，不会串。

`resume_episode` **不在这里清**：它是"这一局从哪一步恢复"的记号，由 `episode`
节点读完才清（它得知道该走哪条路）。

不在这里捕获 `AgentError`——那件事归本文件里的 `episode_error_handler`（F4）。

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

from pokemon_agent.brain import Goal, Task
from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp

from ..deps import HarnessDeps
from .run_state import RunState


def project_goals(goals: list[Task]) -> list[Goal]:
    """把目标栈投影成子图要的形状（D2-②）。

    `goals`（`list[Task]`）是**"目标栈"这个领域概念**，父侧不动；
    `episode_goals`（`list[Goal]`）是**同一次派发算出来的投影视图**——
    两者是不同的东西，所以是两个键。这一笔原先只发生在 `dispatch` 传参
    （`stack=state.goals`），现在**同时写进 state**：内置子图之后，子图的初值
    只能从父 state 的**同名键**来（F1/F8），而子侧的名字是 `episode_goals`。
    """
    return [Goal(goal=t.goal, criteria=t.success_criteria) for t in goals]


def dispatch(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """备好这一局：`episode_id` / `task` / `episode_goals` / `attempts+1` / run 级快照。

    后置条件：`episode_id` 非空且与 `resume_episode` 指向一致（恢复路径）；
    `deps.run_state_snapshot` 是**本局派发时**的 `RunState.model_dump()`。

    `deps.run_state_snapshot` 的写入点从"方法与节点入口"搬到这里（D11-(3)）：
    存档里的 run 级状态**必须跟这一局一起落盘**（PLAN_checkpoint §3/§4 v5）——
    进程死在本局任何时刻，恢复时读那一步的 checkpoint 就能同时拿回两层状态。
    """
    assert state.goals, "dispatch() called with an empty goal stack"
    assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
    top = state.goals[-1]
    episode_id = f"{state.run_id}-ep{len(state.outcomes) + 1}"
    if state.resume_episode is not None:
        assert state.resume_episode.episode_id == episode_id, (
            f"resume target mismatch: {state.resume_episode.episode_id} != {episode_id}"
        )

    runtime.context.run_state_snapshot = state.model_dump()
    return {
        "episode_id": episode_id,
        "task": top,
        "episode_goals": project_goals(state.goals),
        "attempts": state.attempts[:-1] + [state.attempts[-1] + 1],
    }


def episode_error_handler(state: RunState, error: NodeError) -> Command:
    """**单局异常不崩掉整个 run** 的落点（F4 的 `error_handler`）。

    原先这段逻辑是 `dispatch` 里的 `except AgentError`；内置子图之后"父图调用
    那一格"没了，异常由 LangGraph 交给 handler。实测（F4）：handler 拿到的是
    **父 state**，返回 `Command(goto="reflect", update=…)` 时流程正常继续；
    只返回 dict 的话图会停在这一格（所以必须用 `Command`）。

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
        goto="reflect",
        update={
            "outcome": FromRunHarnessToEpisodeHarnessRunResp(
                episode_id=state.episode_id,
                success=False,
                steps=0,
                reason=f"error: {type(exc).__name__}",
            )
        },
    )


__all__ = ["dispatch", "episode_error_handler", "project_goals"]
