"""`EpisodeHarness` 与 `GameToolPort`（世界）交互专用的工具函数。

**只放这一根依赖会用到的重试循环**——跟 `brain_utils.py`/`memory_query_utils.py` 是同一个
原则在 harness 各根依赖上各自的落地：互不依赖，谁的循环谁重试。

**账不在这里写。** 本模块只交回"每一次尝试的原始材料"（`ModelCallLog`）与观测／画面，
落账由宿主做（`EpisodeHarness._perceive` 调 `trace_write.append_model_calls`）。规则是
"账写在它的宿主里"，取舍与代价见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4。

依赖注入的编排函数：端口是**参数**、不是 `self` 属性——调用方（`EpisodeHarness`
的节点方法）传自己的 `self._game` 进来，这里就能用假端口独立测试，不用起一个真的
`EpisodeHarness`。
"""

from __future__ import annotations

from pokemon_agent.errors import PerceptionAttemptFailed
from pokemon_agent.providers import ModelCall
from pokemon_agent.tools.interface import GameToolPort
from pokemon_agent.world import Observation

from .trace_write import ModelCallLog

PERCEPTION_MAX_RETRIES = 2
"""感知重试预算：一帧最多问几次视觉模型。循环在这里不在 World。"""


def perceive_with_retry(
    game: GameToolPort,
    *,
    ram_only: bool = False,
) -> tuple[Observation | None, str | None, ModelCallLog]:
    """反复问一次感知，直到成功或预算耗尽——**循环与端口调用在这里**，
    `perceive_once()` 只负责单次尝试（见 `docs/ROADMAP.md`）。

    `ram_only=True` 时不问模型：交回的观测只有内存那半，`log` 是空的
    （没有 `MODEL_CALL` 要记），因而**不会失败、也不会重试**。

    步骤 1：问一次感知，失败就把这次的账收进 `log`（`attempt` 由这里定，盖章在
    渲染层），继续下一次尝试。
    步骤 2：成功返回 `(观测, base64 PNG, log)`——一次感知可能有多条 call，
    逐条收进 `log`（同一个 `attempt`）。
    步骤 3：预算耗尽返回 `(None, None, log)`——**收场归调用方**（抛
    `PerceptionFailure`），因为账要由宿主写。

    **截图从这条路径上摘下来了。** 帧和"这次模型调用"是两件事：`MODEL_CALL`
    记的是喂给模型的东西，而链中间的键只读内存、压根没有这次调用——图要是挂在
    它上面，那些步就永远没有图。帧改由调用方挂到产出它的那一步的事件上
    （`perceive_after_action` 的 `AFTER_ACTION`），
    **帧的可得性从此与"有没有人看过它"无关**。
    """
    log: ModelCallLog = []
    for attempt in range(1, PERCEPTION_MAX_RETRIES + 1):
        # 步骤 1：问一次感知。
        try:
            result = game.perceive_once(ram_only=ram_only)
        except PerceptionAttemptFailed as exc:
            # 步骤 2：失败，把账收进 log，进入下一次尝试。
            raw = exc.call.get("raw", "")
            log.append(
                (
                    attempt,
                    ModelCall(
                        payload=exc.call,
                        error_kind="PerceptionParseFailure",
                        error=raw,
                    ),
                )
            )
            continue

        # 步骤 3：成功——逐条收账，交回观测 + 这一帧的画面。
        log.extend((attempt, ModelCall(payload=call)) for call in result.calls)
        return result.observation, result.frame_png, log

    # 步骤 4：预算耗尽——材料交回调用方，由它决定怎么收场。
    return None, None, log
