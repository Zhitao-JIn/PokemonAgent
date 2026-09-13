"""`record_observation`：把当前帧记成一条 `OBSERVE`——**这一链的决策输入**。

图上它在链首、`judge` 之前，是这一格唯一的记账点：`OBSERVE` 必须落在**每条链**上
（决策输入一次一条），链内每个键都没有它——链内那些键只读 RAM（`perceive_once`
的 `ram_only=True`，本来就没有 `MODEL_CALL` 可挂），痕迹留在那一键自己的
`AFTER_ACTION` 上（轻量摘要，不含完整 `facts`，也不承载 `goals`）。这一格没了，
replay 与观测台就没有"大脑当时看到的世界"的结构化原件了。

**它不扶正、不盖步号**：`observation` 在每步的终点（`press/close_step`）就前进到位
了，开局那一帧由 `entry.begin_episode` 直接产出。扶正曾经住在这里——那时它是
"步级 + 链级"的混合节点（扶正每步一次、`OBSERVE` 每链一次）；链内小循环让链内每步
都不再经过它，扶正遂失去宿主，挪去了 `close_step`
（见 `docs/spec/harness/PLAN_graph_readability.md` §3.4）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...deps import HarnessDeps
from ..episode_frames import frame_b64
from ..episode_state import EpisodeRunState


def record_observation(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """记一条 `OBSERVE`，把这一帧的原始画面挂上。只记账，不改状态。

    **它带的那一帧有两个来源**（帧的承载规则见 `episode_harness` 模块文档最后两条）：

    - **开局那一帧**（`entry.begin_episode` 感知的，没有前驱按键）：从
      `deps.pending_frames` 取，取走即删；
    - **上一条链链尾那一帧**：链尾键自己那份挂在它的 `AFTER_ACTION` 上，这一份由
      `frames.frame_b64` **按 event_id 读回**（v7 取代 v5 的"多带一份"）——好让链首
      这一页自带"大脑决策时看到的世界"。

    PNG 进不了领域模型 `Observation`，所以两者都要在挂账这一刻现取现用。

    前置条件：`state.observation` 非空（链首进图前必然已有一帧）。
    后置条件：返回空增量（**本节点不改任何 state 字段**，只往 trace 与帧登记表写）。
    """
    deps = runtime.context
    obs = state.observation
    assert obs is not None, "record_observation before an observation exists"

    # 步骤 1：取这一帧——开局那一帧进暂存表取；否则按 event_id 读回上一条链链尾那
    # 一帧（`frame_b64` 只认登记表，未登记即 None，缺图跳过）。两条路径都可能给
    # None（这一帧本来就没落图，或链首恰好没有前驱按键产出的那一份）。
    frame_png = deps.pending_frames.pop((state.episode_id, obs.step), None)
    if frame_png is None:
        frame_png = frame_b64(deps, state.episode_id, obs.step)

    # 步骤 2：记 OBSERVE，把这一帧的原始画面挂上。
    event_id = deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.OBSERVE,
            episode_id=state.episode_id,
            step=obs.step,
            obs=obs,
            goals=state.episode_goals,
            frame_png=frame_png,
        )
    )
    # 有帧才登记（没帧的 OBSERVE 不产生截图文件，登记它会让 `frame_b64` 去读一个
    # 不存在的文件）；**已有登记的不覆盖**——登记表的规则是"谁先产出这一帧谁登记"：
    # 每一键的帧都由 `press/perceive_after_action` 那条 `AFTER_ACTION` 先登记（读哪次
    # 都一样，但指向必须**稳定**，不能同一时刻问两次答两个事件），只有第 0 步这一帧
    # 没有前驱按键，才由本格登记。
    if frame_png is not None and (state.episode_id, obs.step) not in deps.frame_event_ids:
        deps.frame_event_ids[(state.episode_id, obs.step)] = event_id
    return {}
