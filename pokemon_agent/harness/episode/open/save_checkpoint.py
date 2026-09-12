"""`save_checkpoint`：每圈边界（含 step0）写一份存档，再补一条接缝账。只写不改
状态——返回空增量。

**为什么存档的粒度是"链边界"而不是"每键"**：每键一份含模拟器快照的存档会让存档量
乘上链长（`times=N` 就把存档翻 N 倍），而链内执行是纯 RAM 确定的——从链首存档重放
能逐帧复现，链内不必存。所以它排在链首这一格（`PLAN_checkpoint` §2）。

**为什么它必须在图内、不能留在图外**：步 2 之前它是 `EpisodeHarness._close` 隔壁的
一个方法，入口在图外；内置子图之后没有"方法入口"这个位置了，而这一格的时机恰好是
图告诉它的（每圈回到链首），所以它就是图里的一格。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_frames import frame_ledger
from ..episode_state import EpisodeCheckpoint, EpisodeRunState


def save_checkpoint(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """写存档并把这一笔标在事件流里。

    三件套：模拟器世界快照 + `EpisodeRunState` + trace 游标；v6 起再带上
    **本局帧账**（见 `frames.frame_ledger`——纯内存态，不带就等于恢复后丢图）。

    存档成功后补一条 `CHECKPOINT_SAVE`（`LIFECYCLE`），与恢复端的
    `CHECKPOINT_RESTORE` 对称——存档端也要在事件流里可见，否则 replay 只能反推
    存档文件的 step 来切段。

    `checkpoint_root` 未装配（测试、单局直跑）时空转，**且不写账**：没有存档就没有
    接缝可标。这一条不是省事——写了 `CHECKPOINT_SAVE` 却没有对应文件，replay 会在
    那里切出一个空段。

    前置条件：`state.episode_id` 非空（由 `episode_id` 是子图入口断言保证）。
    后置条件：返回空增量（**本节点不改任何 state 字段**）。
    """
    deps = runtime.context
    root = deps.checkpoint_root
    if root is None:
        return {}
    # 步骤 1：摊平本局帧账——它必须在存档里，且只有本局那一段有意义。
    frame_event_ids, pending_frames = frame_ledger(deps, state.episode_id)
    # 步骤 2：写存档：世界快照 + 本局状态 + run 级状态 + trace 游标 + 本局帧账。
    EpisodeCheckpoint(
        run_id=deps.run_id,
        episode_id=state.episode_id,
        step=state.step,
        episode_state=state,
        run_state_dump=deps.run_state_snapshot or {},
        last_event_id=deps.trace.cursor(),
        emulator_state=deps.game.save_state_bytes().emulator_state,
        frame_event_ids=frame_event_ids,
        pending_frames=pending_frames,
    ).write(root)
    # 步骤 3：存档端留一个接缝标记（量级是**链边界一条**，不是每键一条）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECKPOINT_SAVE,
            episode_id=state.episode_id,
            step=state.step,
            saved_step=state.step,
        )
    )
    return {}
