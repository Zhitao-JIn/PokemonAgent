"""`act` 格（episode 层）：**派一个 task**——任务表里第一条 PENDING 标 RUNNING、拼 `TaskInput`、
经 `task_entry.run_task` 跑完 task 子图，把 `TaskOutput` 写进 `pending_task`。

吸收结算（键数、失败连击）在下一圈的 `perceive`，盖章在下一圈的 `review_and_judge`；
本格出口无条件回 `perceive`。

**task 抛错由本格接住**（谁接住谁记账）：记 `task_error`；`AgentError`（预期内的单个 task
失败）兜成一份 `ERROR` 的 `TaskOutput`——这一局照常往下走，review 把它盖成 FAILED；
别的异常是 bug，记完原样上抛。
task 子图由装配点（`build.py`）编译，经 `runtime.context.task_graph` 递来。
派发（`dispatch_task`）与异常收场（`settle_task_error`）各住一个文件，恢复路径（`harness/checkpoint`）复用同一份。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...task.task_entry import run_task
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState
from .dispatch_task import dispatch_task
from .settle_task_error import settle_task_error


def act(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """派第一条 PENDING，返回 `{"pending_task", "tasks", "step"}`。

    前置条件：任务表里有 PENDING（`plan_episode` 保证）。
    """
    # 步骤 1：标 RUNNING，装配 TaskInput。
    dispatched = dispatch_task(state)
    task_input = dispatched["task_input"]

    # 步骤 2：跑 task 子图，结算交给下一圈 perceive 吸收、review 盖章；抛错由本格接住。
    try:
        output = run_task(runtime.context.task, runtime.context.task_graph, task_input=task_input)
    except Exception as exc:
        output = settle_task_error(runtime.context, task_input, exc, source="episode.act")
    return {"pending_task": output, "tasks": dispatched["tasks"], "step": dispatched["step"]}


__all__ = ["act", "dispatch_task", "settle_task_error"]
