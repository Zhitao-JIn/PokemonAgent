"""`detect_stall` 与判定纯函数 `compute_stall`。

**算数与判断分离**：本格只算"这一步的停摆键与连续计数"并记一条快照，
**达到 `STALL_LIMIT` 时的强制终止判断在下一轮 `gate/judge`**（它是图上唯一的终止判定
节点）。所以 `STALL_LIMIT` 的两个读者都不是本文件（是 `gate/judge` 与
`close/close_episode`），它住顶层 `pokemon_agent/config.py`——本格只负责把
`stall_count` 算出来，阈值多少与本格无关。

STALL_CHECK 快照的动机（每一步的构成过程可回看，不用重放整局）见 `CHANGELOG.md`
2026-09-03 条目。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.world import Observation

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def compute_stall(
    after: Observation, action: Action, prev_key: str, prev_count: int
) -> tuple[str, int]:
    """算这一步的停摆键（画面机械状态 + 动作描述）与更新后的连续计数。

    跟上一步全同 → 计数 +1，否则清零重计一次。
    """
    key = f"{after.stall_key()}|{action.describe()}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count


def detect_stall(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """算停摆键与连续计数，记一条 STALL_CHECK 快照。

    **只改 `stall_key`/`stall_count` 两处状态字段 + 写一条账，不碰观测。**

    前置条件：`observation`/`action`/`pending_observation` 非空（本圈前三格已跑过）。
    后置条件：返回 `{"stall_key": …, "stall_count": …}`。
    """
    deps = runtime.context
    assert state.observation is not None, "detect_stall before record_observation"
    assert state.action is not None, "detect_stall without an action"
    assert state.pending_observation is not None, "detect_stall before act"
    key, count = compute_stall(
        state.pending_observation, state.action, state.stall_key, state.stall_count
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.STALL_CHECK,
            meta={
                "source": "detect_stall",
                "episode_id": state.episode_id,
                "step": state.observation.step,
            },
            # 封套上的 `source` = 发这条账的节点名（`kind` 只说"哪本账"）。
            stall_key=key,
            stall_count=count,
        )
    )
    return {"stall_key": key, "stall_count": count}
