"""`store_step_episode_memory`：把 `act` 刚推进的这一步反思成一条情景记忆，落库。

**不改状态字段，只落库记账。**

情景记忆记"我在那种画面里选了什么"（一次经过）；`before`/`action`/`after` 都从 state
直接读，跟 `press/detect_stall`/`press/close_step`/`store_object_semantic_memory` 读的是
同一份、互不影响谁先跑。

**盖三样章**（都是 harness 自己的事，跟"盖 `episode_id`"同一个道理）：`episode_id`
（大脑不知道自己在哪一局）、`run_id`（大脑不知道磁盘上的存储约定）、
`before_frame`/`after_frame` 两张截图的 base64（两次感知的 event_id 都登记在
`deps.frame_event_ids`，见 `episode_frames.frame_b64`）。直接存 base64 的取舍见
`CHANGELOG.md` 2026-09-05 条目。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolReflectReq,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_frames import frame_b64
from ..episode_state import EpisodeRunState


def store_step_episode_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """反思这一步并落一条情景记忆。**不改状态字段，返回空增量。**

    前置条件：`observation`/`action`/`pending_observation` 非空（本圈前三格已跑过）。
    """
    deps = runtime.context
    assert state.observation is not None, "store_step_episode_memory before record_observation"
    assert state.action is not None, "store_step_episode_memory without an action"
    assert state.pending_observation is not None, "store_step_episode_memory before act"
    ep, before, action, after = (
        state.episode_id,
        state.observation,
        state.action,
        state.pending_observation,
    )

    # 步骤 1：反思成一条情景记忆，并盖上那三样。
    # `before_frame` 是第 `before.step` 步的开局画面，`after_frame` 是
    # 第 `before.step + 1` 步的开局画面（= 这一步做完动作后的画面）。
    entry = deps.brain_tool.reflect(
        FromHarnessToBrainToolReflectReq(before=before, action=action, after=after)
    ).entry.model_copy(
        update={
            "episode_id": ep,
            "run_id": deps.run_id,
            # `stop` 由这里盖章，不在大脑里——"这一键之后为什么没有继续按键"是这一圈的
            # 结局，而 `reflect` 只看得见前后两帧（它算得出"撞墙了"却算不出"链被作废了"，
            # 那件事在 `press/perceive_after_action` 判完才成立）。
            "stop": state.pending_stop,
            # 同 `stop`：`reflect` 只看得见前后两帧，它不知道"这一键属于哪次决策"。
            # 归属是执行期的事（`decide/think_action` 盖的 `plan_step_start`）。
            "plan_step_start": state.plan_step_start,
            "before_frame": frame_b64(deps, ep, before.step),
            "after_frame": frame_b64(deps, ep, before.step + 1),
        }
    )

    # 步骤 2：落库。
    deps.memory.store_episode_step(FromHarnessToMemoryToolStoreEpisodeStepReq(entry=entry))
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.MEMORY_WRITE,
            episode_id=ep,
            step=before.step,
            entry=entry,
        )
    )
    return {}
