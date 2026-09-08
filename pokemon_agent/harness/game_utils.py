"""`EpisodeHarness` 与 `GameToolPort`（世界）交互专用的工具函数。

**只放这一根依赖会用到的重试循环与记账**——跟 `brain_utils.py`/
`memory_query_utils.py` 是同一个原则在 harness 各根依赖上各自的落地：
互不依赖，谁的循环谁记账。

依赖注入的编排函数：端口是**参数**、不是 `self` 属性——调用方（`EpisodeHarness`
的节点方法）传自己的 `self._game`/`self._trace` 进来，这里就能用假端口
独立测试，不用起一个真的 `EpisodeHarness`。
"""

from __future__ import annotations

from pokemon_agent.errors import PerceptionAttemptFailed, PerceptionFailure
from pokemon_agent.interfaces import GameToolPort, TraceToolPort
from pokemon_agent.schemas.communication import (
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.datastore import Source
from pokemon_agent.schemas.domain import ModelCall, ObservationFromWorld

PERCEPTION_MAX_RETRIES = 2
"""感知重试预算：一帧最多问几次视觉模型。循环在这里不在 World。"""


def perceive_with_retry(
    game: GameToolPort,
    trace: TraceToolPort,
    episode_id: str,
    step: int,
    *,
    screenshot_step: int | None = None,
) -> ObservationFromWorld:
    """反复问一次感知，直到成功或预算耗尽——**循环、端口调用、记账都在这里**，
    `perceive_once()` 只负责单次尝试（见 `docs/ROADMAP.md`）。

    步骤 1：问一次，失败就记一条账（`attempt` 由这里传给 req，盖章在 tool），
    继续下一次尝试。
    步骤 2：成功就记账，把这一帧原始画面（PNG 字节）随成功的那条 `MODEL_CALL`
    一起落盘，交回观测。
    步骤 3：预算耗尽仍没成功，升级成 `PerceptionFailure`——这一步彻底完了。

    `frame_png` 直接挂在这条 perception 的 `MODEL_CALL` 事件上：这次调用
    实际喂给视觉模型的东西（文字 prompt + 这张截图）就该记在它真正发生的
    地方，在这里放进 req，不绕道 `EpisodeRunState`/`look()`。调用方不用关心
    帧字节，只要观测。

    screenshot_step：透传给 trace 的截图文件名 step 号，缺省等于
    `step`。`look_after_action()` 会传 `step + 1`——它感知到的是下一步的开局
    画面，`StepMemory.before_frame`/`after_frame` 按"这张图是第几步的开局
    画面"编号，两边要对得上，见 `LocalTrace.append()` 的说明。
    """
    last_raw = ""
    for attempt in range(1, PERCEPTION_MAX_RETRIES + 1):
        # 步骤 1：问一次感知。
        try:
            result = game.perceive_once()
        except PerceptionAttemptFailed as exc:
            # 步骤 2：失败，记账，进入下一次尝试。
            last_raw = exc.call.get("raw", "")
            trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.MODEL_CALL,
                    episode_id=episode_id,
                    step=step,
                    source=Source.PERCEPTION,
                    call=ModelCall(
                        payload=exc.call,
                        error_kind="PerceptionParseFailure",
                        error=last_raw,
                    ),
                    attempt=attempt,
                )
            )
            continue

        # 步骤 3：成功，记账（连同这一帧原始画面一起落盘），交回观测。
        for call in result.calls:
            trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.MODEL_CALL,
                    episode_id=episode_id,
                    step=step,
                    source=Source.PERCEPTION,
                    call=ModelCall(payload=call),
                    attempt=attempt,
                    frame_png=result.frame_png,
                    screenshot_step=screenshot_step,
                )
            )
        return result.observation

    # 步骤 4：预算耗尽，升级成 PerceptionFailure。
    raise PerceptionFailure(PERCEPTION_MAX_RETRIES, f"unparsable output: {last_raw!r}")
