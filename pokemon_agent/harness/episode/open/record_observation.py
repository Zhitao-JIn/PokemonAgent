"""`record_observation`：把当前帧记成一条 `OBSERVE`——**这一链的决策输入**。

图上它在链首、`judge` 之前，是这一格唯一的记账点：`OBSERVE` 必须落在**每条链**上
（决策输入一次一条），链内每个键都没有它——链内那些键只读 RAM（`perceive_once`
的 `ram_only=True`，本来就没有 `MODEL_CALL` 可挂），痕迹留在那一键自己的
`AFTER_ACTION` 上（轻量摘要，不含完整 `facts`，也不承载 `goals`）。这一格没了，
replay 与观测台就没有"大脑当时看到的世界"的结构化原件了。

**它不扶正、不盖步号**：`observation` 在每步的终点（`press/close_step`）就前进到位
了，开局那一帧由 `entry.begin_episode` 直接产出。扶正曾经住在这里——那时它是
"步级 + 链级"的混合节点（扶正每步一次、`OBSERVE` 每链一次）；链内小循环让链内每步
都不再经过它，扶正遂失去宿主，挪去了 `close_step`。

**这一帧的原始画面跟着这条账走**（0914 曾删、同日跟进请回）：从帧槽按
`obs.step` 现取（`episode_frames.frame_b64`）——正常单进程跑必然命中（这一帧
就是上一个感知格刚产出的）；跨进程恢复时槽是空的，那时这条账**没有 `frame` 键**
（不写 `null`），replay 缺这张图是预期内的。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...deps import HarnessDeps
from ..episode_frames import frame_b64
from ..episode_state import EpisodeRunState


def record_observation(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """记一条 `OBSERVE`（这一链的决策输入）。只记账，不改状态。

    前置条件：`state.observation` 非空（链首进图前必然已有一帧）。
    后置条件：返回空增量（**本节点不改任何 state 字段**，只往 trace 写）。
    """
    deps = runtime.context
    obs = state.observation
    assert obs is not None, "record_observation before an observation exists"

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.OBSERVE,
            meta={"source": "record_observation", "episode_id": state.episode_id, "step": obs.step},
            # 封套上的 `source` = 发这条账的节点名（`kind` 只说"哪本账"）。
            obs=obs,
            goals=state.episode_goals,
            frame=frame_b64(deps, state.episode_id, obs.step),
        )
    )
    return {}
