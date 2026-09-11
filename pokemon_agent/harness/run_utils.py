"""`RunHarness`（run 级图）自己的图控制纯函数——跟哪一根依赖都不绑定。

**只放和图控制最相关、不属于任何一根依赖的部分**——目标栈怎么变、trace
里怎么挑出一局的完整记录。跟 `run_plan_utils.py`（只放"问规划模型"这一根
依赖会用到的重试循环、记账与纯计算）是同一层拆分，跟 `episode_utils.py`
又是同一个原则在两层图上各自的落地，两边**互不依赖**：run 层不越过
`EpisodeHarnessPort` 直接拿子 agent 的工具函数用，episode 层也不知道
run 层的存在。

`history_lines`/`goals_lines`（trace 事件/目标栈折成 prompt 文本）在
`pokemon_agent.prompts.run_plan`——按项目约定，struct→text 是 prompts 层的事。
"""

from __future__ import annotations

from pokemon_agent.schemas.frontend import FromFrontendToRunHarnessSubmitEditReq
from pokemon_agent.trace import TraceEvent

from .interface import MAX_GOAL_RETRIES, RunState


def episode_trace_events(events: list[TraceEvent], episode_id: str) -> list[TraceEvent]:
    """从全量事件流里挑出单个 episode 的完整 trace（`events` 已按 event_id
    升序，见 `TracePort.events`，这里原序保留）。

    `TracePort.events` 只支持按 `EventType` mask，不支持按 `episode_id`
    过滤——`review()` 节点要把"刚跑完那一局的完整 trace"塞进
    `FromHarnessToReviewerReviewReq.episode_trace`，这里在 Python 侧按
    `episode_id` 筛一遍（调用方传 `events(None)` 的全量结果进来）。
    """
    return [ev for ev in events if ev.episode_id == episode_id]


def goal_retries_exhausted(attempts_used: int) -> bool:
    """判断栈顶目标的重试预算是否耗尽。

    `attempts_used` 是 `dispatch` 已经把这个目标派发过的次数（这次失败也
    算一次派发，`reflect()` 调这个函数前已经 +1 过）；减 1 换算成"已经
    重试过几次"，达到或超过 `MAX_GOAL_RETRIES` 就是预算耗尽——`reflect()`
    据此决定强制弹栈还是直连重试。
    """
    retries_used = attempts_used - 1
    return retries_used >= MAX_GOAL_RETRIES


def apply_goals_edit(state: RunState, edit: FromFrontendToRunHarnessSubmitEditReq) -> None:
    """把观测台的编辑指令应用到当前目标栈（原地改 `state`）：整栈原子替换、
    不锁栈顶——前端把目标栈变成纯本地草稿（含栈顶），只在 review 阶段可
    编辑，点 push 时一次性把整份草稿同步过来。


    `attempts` 按 `task_id` 找回旧计数，新目标（`task_id` 没出现过）记 0。
    """
    old_attempts = dict(zip((g.task_id for g in state.goals), state.attempts))
    state.goals = list(edit.goals)
    state.attempts = [old_attempts.get(g.task_id, 0) for g in edit.goals]
