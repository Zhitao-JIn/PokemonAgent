"""`act` 格（run 层）：**派一局**——`dispatch` 选目标、拼 `EpisodeInput`，经
`episode_entry.run_episode` 跑完 episode 子图，把 `EpisodeOutput` 写进 `pending_episode`。

吸收在下一圈的 `perceive`、盖章在 `review_and_judge`；本格出口回 `perceive`（一圈 = 一局）。

**整局抛错由本格接住**（谁接住谁记账，与 episode 层 `act` 接 task 抛错同形）：
补空章（episode 图已经死了，只能由接住它的人代写，保证一局恰好一条 EpisodeMemory）→
记 `episode_error`；`AgentError`（预期内的单局失败）兜成一份 `ERROR` 结算，别的异常原样上抛
（由 `run_entry.new_run` 记 `run_error`）。
episode 子图由装配点（`build.py`）编译，经 `runtime.context.episode_graph` 递来。
派发（`dispatch`）与异常收场（`settle_episode_error`）各住一个文件。
**episode 级存档在本格一开始**（有存档器时）：run 图停在进 `act` 前，这一局还没动过世界与记忆。
**恢复到某个 task 时**（存档器里有恢复计划）：不存档，经 `episode_entry.resume_episode` 从存下的
episode 状态接着跑。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness.domain import EpisodeInput

from ...episode import episode_entry
from ..run_state import RunState
from ..runtime import RunRuntime
from .dispatch import dispatch
from .settle_episode_error import settle_episode_error


def act(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """派一局，返回 `{"goals", "episode_input", "step", "pending_episode"}`。"""
    # 步骤 1：选目标、盖 RUNNING、拼 EpisodeInput（纯函数，还没动任何东西）。
    dispatched = dispatch(state)
    episode_input: EpisodeInput = dispatched["episode_input"]

    # 步骤 2：有恢复计划就不存档（世界与记忆已是目标 task 开局的样子，按 episode 级存会名不副实）；
    # 否则存 episode 级档——存的是进 `act` 前的状态，将派的就是这一局。
    ck = runtime.context.checkpointer
    resumed = ck.take_resume(episode_input.episode_id) if ck is not None else None
    if ck is not None and resumed is None:
        ck.save(
            "episode", run_id=state.run_id, step=state.step, episode_id=episode_input.episode_id
        )

    # 步骤 3：跑 episode 子图（或从存下的状态接着跑），结算交给下一圈 perceive 吸收；
    # 抛错由本格接住。
    try:
        if resumed is None:
            outcome = episode_entry.run_episode(
                runtime.context.episode, runtime.context.episode_graph, episode_input=episode_input
            )
        else:
            outcome = episode_entry.resume_episode(
                runtime.context.episode,
                runtime.context.episode_graph,
                resumed,
                episode_input=episode_input,
            )
    except Exception as exc:
        outcome = settle_episode_error(
            runtime.context.episode, state.run_id, episode_input, exc, source="run.act"
        )

    return {**dispatched, "pending_episode": outcome}


__all__ = ["act", "dispatch", "settle_episode_error"]
