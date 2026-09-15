"""`perceive_after_action`：感知 `act` 刚推进出来的新帧，写这一键的 `AFTER_ACTION`。
本文件同时是**所有感知调用的宿主**（`perceive_once`）。

**重试循环不在这里**（0913 夜）：它搬到了 `GameTools.perceive_with_retry()`
（对齐 `BrainTool._attempt_loop`）。理由与 brain 那五条链路完全同一条——
"试几次、耗尽之后怎么办"是**调用方处境**的知识，循环控制者在 tool 层；
world 抛的 `PerceptionAttemptFailed` 在那一层就被接住、翻译成
`MaxRetriesExceeded`，harness 因此**不认识 world 的异常**，世界的词汇也就
不必继承 `AgentError`（`world/errors.py` 自成一根 `WorldError`）。
本格退化成"交一次 → 落账 → 上抛"，与 `think_action` 对 `BrainTool.choose()`
的分工逐字相同：**成功走返回值里的 `log`，耗尽走异常携带的 `calls`，
落账永远是宿主做的。**

**结局判读已删**（0914 用户定调）：此前这一格还负责 `compute_stop`——纯 RAM 比较
判"撞墙/换图/本局到点"，交给 `apply_stop` 按归因截队列。实际场景远比三个谓词复杂，
判不准的判断比没有判断更坏（真机实测：`blocked` 归因抢在预算兜底前面，3 步预算
跑出 4 步）。预算的执行改为 `close_step` 那道**纯步数**的闸——超没超上限是零判断
的；撞没撞墙不再判、也不再截队列，模型交出的链**照单全按**。

感知分两档：

- **链中间的键只读内存**：判读删了之后链中间的键什么都不需要判，只为留下
  "这一键之后世界长什么样"的痕迹；为此烧一次视觉调用买的全是用不上的信息
  （场景、对话），而且会让链的执行结果依赖模型返回——"同存档 + 同链 →
  同一状态"当场失效。
- **链尾那一键做完整感知**：那一帧要交给 `gate/judge` 看。`MODEL_CALL(PERCEPTION)`
  的条数与判读时代相等（验收不变量，§9）。

**账也在这里写**：本格是帧的产出格，所以这一帧进覆盖式帧槽（步尾 `StepMemory` 的
`before_frame`/`after_frame` 从那儿取），而链内每键一条的观察账 `AFTER_ACTION`
（这一帧 RAM 免费的那一半 + 原始画面）也在这里落——RAM 档**照截帧**，图的可得性
与"有没有人看过它"无关，所以每个键都有图可带。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_frames import remember_frame
from ..episode_state import EpisodeRunState


def perceive_once(
    deps: HarnessDeps,
    episode_id: str,
    step: int,
    *,
    source: str,
    ram_only: bool = False,
) -> tuple[Any, str | None]:
    """感知一帧，并把这次的尝试账落进 trace——**两个感知调用点的共同宿主**。

    调用点有两个：本文件的节点 `perceive_after_action`（图内）与
    `episode_entry.begin_episode`（图外的局入口）。两者都走
    `deps.game.perceive_with_retry()`（循环与重试预算都在那里），而**账按
    "写在它的宿主里"这条规则统一落在这里**——于是 `MODEL_CALL(PERCEPTION)`
    与消费它的那一格在同一个函数里。

    `source` 由**调用方自报**（`perceive_after_action` / `episode_entry.begin_episode`）
    ——这条账从哪个位置发出只有调用方知道，与本宿主函数无关。

    前置条件：`episode_id` 非空、`source` 非空。
    后置条件：返回 `(观测, base64 PNG | None)` 成对；预算耗尽时抛
    `MaxRetriesExceeded`（`source="perception"`）——**账已经写完**，重试期间
    烧掉的 token 一条不少。"耗尽之后这一局怎么收场"不在这里决定：那是
    `episode_error_handler` 的事（它捕的是同一个 `AgentError` 家族）。
    `ram_only=True` 时压根不问模型（`log` 为空，`append_model_calls` 对空账
    合法且不写事件），因此不会走到失败分支。
    """
    try:
        resp, log = deps.game.perceive_with_retry(ram_only=ram_only)
    except MaxRetriesExceeded as exc:
        # 预算耗尽——整条失败账挂在异常上。落账后**原样上抛**（怎么收场归
        # `episode_error_handler`；本格的职责只是保证账不缺）。
        deps.trace.append_model_calls(
            FromHarnessToTraceToolAppendModelCallsReq(
                meta={"source": source, "episode_id": episode_id, "step": step},
                kind=TraceKind.PERCEPTION_CALL,
                log=list(exc.calls),
            )
        )
        raise

    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            meta={"source": source, "episode_id": episode_id, "step": step},
            kind=TraceKind.PERCEPTION_CALL,
            log=list(log),
        )
    )
    return resp.observation, resp.frame_png


def perceive_after_action(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """感知新帧、写 `AFTER_ACTION`。**只改 `pending_observation` 一处。**

    前置条件：`state.observation` 非空（前两格 `act` 已跑过）。
    后置条件：返回 `{"pending_observation": …}`；有帧时把它记进覆盖式帧槽
    （`episode_frames.remember_frame`）——步尾的 `store_step_episode_memory`
    从那两个位取 `before_frame`/`after_frame`。
    """
    deps = runtime.context
    assert state.observation is not None, "perceive_after_action before act"
    ep, before = state.episode_id, state.observation
    # `act` 已经弹掉队首，所以"队列空"就是"刚按的这一个是链尾"。
    is_decision_tail = not state.pending_presses

    # 步骤 1：感知（循环在 `GameTools.perceive_with_retry()`，账在本函数里落）。
    # 链尾直接走完整档，链中间的键只读内存。账的步号取 `before.step`——与 `ACT`
    # 落在同一步上。
    obs, frame_png = perceive_once(
        deps, ep, before.step, source="perceive_after_action", ram_only=not is_decision_tail
    )

    # 步骤 2：**给这一帧盖上它自己的步号**——它是"第 `before.step + 1` 步的开局画面"。
    # `close_step` 拿它当新 `observation` 时步号只加一，两处必须同值（不变式
    # `observation.step == step`）；不同值的话 `(episode_id, step)` 这个记忆键会从第二步
    # 起就错位，`before_frame`/`after_frame` 也跟着查错。
    obs = obs.model_copy(update={"step": before.step + 1})

    # 步骤 3：写这一键的观察账（`AFTER_ACTION`）——**账写在它的宿主里**：这一键在本格
    # 产出，账就挂在本格。正文 = 这一帧 RAM 免费的那一半（结构化），原始画面
    # （`frame_png`，RAM 档也照截）跟着账走；步尾的 `store_step_episode_memory`
    # 照旧从帧槽取 `before_frame`/`after_frame`。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.AFTER_ACTION,
            meta={"source": "perceive_after_action", "episode_id": ep, "step": before.step},
            obs=obs,
            frame=frame_png,
        )
    )
    if frame_png is not None:
        remember_frame(deps, ep, before.step + 1, frame_png)

    return {"pending_observation": obs}
