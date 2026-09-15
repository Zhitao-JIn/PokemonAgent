"""`store_step_episode_memory`：把 `act` 刚推进的这一步反思成一条情景记忆，落库。

**不改状态字段，只落库记账。**

情景记忆记"我在那种画面里选了什么"（一次经过）；`before`/`action`/`after` 都从 state
直接读，跟 `press/detect_stall`/`press/close_step`/`store_object_semantic_memory` 读的是
同一份、互不影响谁先跑。

**盖三样章**（都是 harness 自己的事，跟"盖 `episode_id`"同一个道理）：`episode_id`
（大脑不知道自己在哪一局）、`run_id`（大脑不知道磁盘上的存储约定）、
`before_frame`/`after_frame` 两张截图的 base64。两张图从**覆盖式帧槽**取
（`episode_frames.frame_b64`）：本格在每个键的步尾（**链内每个键都过这一格**，不只
链尾那一键），那一刻槽里正好留着"这一步的开局画面"与"本格刚产出的下一步画面"两张，
**零盘 IO**（0914 封套改造后帧槽是画面唯一的取用通道，不再有回盘那级）。
直接存 base64 的取舍见 `CHANGELOG.md` 2026-09-05 条目。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolReflectReq,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

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
        FromHarnessToBrainToolReflectReq(
            before=before, action=action, after=after, episode_id=ep, step=before.step
        )
    ).entry.model_copy(
        update={
            "run_id": deps.run_id,
            "before_frame": frame_b64(deps, ep, before.step),
            "after_frame": frame_b64(deps, ep, before.step + 1),
        }
    )

    # 步骤 2：落库。
    deps.memory.store_episode_step(FromHarnessToMemoryToolStoreEpisodeStepReq(entry=entry))
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_STEP,
            meta={"source": "store_step_episode_memory", "episode_id": ep, "step": before.step},
            # 封套上的 `source` = 发这条账的节点名（`kind` 只说"哪本账"，说不了"谁写的"）。
            entry=entry,
        )
    )
    return {}
