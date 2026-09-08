"""`EpisodeHarness` 与大脑交互专用的工具函数。

**只放这一根依赖会用到的重试循环与记账**——跟 `game_utils.py`/
`memory_query_utils.py` 是同一个原则在 harness 各根依赖上各自的落地：
互不依赖，谁的循环谁记账。

依赖注入的编排函数（`choose_with_retry` 调 `BrainToolPort`/`TraceToolPort`）：
端口是**参数**、不是 `self` 属性——调用方（`EpisodeHarness` 的节点方法）
传自己的 `self._brain`/`self._trace` 进来，这里就能用假端口独立测试，
不用起一个真的 `EpisodeHarness`。`choose_with_retry` 不碰 `GameToolPort`：
决策是同步调用，不需要在等待期间演化世界。

**`choose_with_retry` 直接 import `pokemon_agent.prompts.decide_action`
自己拼重试纠正说明**：拼 prompt 是 Harness 的事，`Brain` 只认现成的
字符串（`choose_once(req, prompt)`）——`Brain` 不提供、也不该提供
`retry_prompt()` 这类方法，那会让它重新知道 prompt 内容怎么来。
"""

from __future__ import annotations

from pokemon_agent.errors import DecisionAttemptFailed, MaxRetriesExceeded
from pokemon_agent.interfaces import BrainToolPort, TraceToolPort
from pokemon_agent.prompts import decide_action as decide_action_prompt
from pokemon_agent.schemas.communication import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.datastore import Source
from pokemon_agent.schemas.domain import ActionFromBrain, ModelCall

DECISION_MAX_RETRIES = 3
"""决策重试预算：一次决策最多问几次模型。重试循环在这里（不在 Brain）——
"谁控制循环，谁记账"，见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"。"""


def choose_with_retry(
    brain_tool: BrainToolPort,
    trace: TraceToolPort,
    episode_id: str,
    step: int,
    req: FromHarnessToBrainToolChooseOnceReq,
) -> tuple[ActionFromBrain, int]:
    """反复问一次决策，直到成功或预算耗尽——**循环、端口调用、记账都在这里**，
    `choose_once()` 只负责单次尝试（见 `docs/ROADMAP.md`）。

    `req.prompt` 是首次尝试用的基础 prompt（调用方已经拼好回填过）；重试时
    `req.model_copy(update={"prompt": ...})` 换掉这一个字段再传给
    `choose_once(req)`，`req` 其余字段（`space` 等）原样带着，不用再传
    第二个参数。

    **同步调用**：无头模式下世界不限速（见
    `pokemon_agent/world/pyboy_world.py`），决策等待期间演化世界省不出时间
    ——tick 本身就是瞬间的，异步 + 轮询 `future.done()` 反而是多余的复杂度。
    直接同步调 `choose_once()`，拿到结果（或异常）就往下走。

    步骤 1：问一次、记账，失败就带纠正提示进入下一次尝试。
    步骤 2：预算耗尽仍没成功，补一条 ERROR，升级成 `MaxRetriesExceeded`。
    成功返回 `(动作, 命中的第几次尝试)`——记账已经在这里做完，调用方只需要写
    自己那类"选定"事件（比如 `THINK`）。
    """
    base_prompt = req.prompt
    last_call: ModelCall | None = None
    for attempt in range(1, DECISION_MAX_RETRIES + 1):
        # 步骤 1：问一次，记账；失败就带纠正提示重试。
        try:
            resp = brain_tool.choose_once(req)
            action, call = resp.action, resp.calls[0]
        except DecisionAttemptFailed as exc:
            call = exc.call
            trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.MODEL_CALL,
                    episode_id=episode_id,
                    step=step,
                    source=Source.DECISION,
                    call=call,
                    attempt=attempt,
                )
            )
            last_call = call
            retry_req = decide_action_prompt.RetryPromptReq(
                base_prompt=base_prompt,
                attempt=attempt + 1,
                reason=call.error,
                raw=call.payload.get("raw", "")[:400],
            )
            req = req.model_copy(update={"prompt": decide_action_prompt.retry_prompt(retry_req)})
            continue

        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MODEL_CALL,
                episode_id=episode_id,
                step=step,
                source=Source.DECISION,
                call=call,
                attempt=attempt,
            )
        )
        return action, attempt

    # 步骤 2：预算耗尽，补一条 ERROR，升级成 MaxRetriesExceeded。
    assert last_call is not None
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.DECISION_FAILED,
            episode_id=episode_id,
            step=step,
            call=last_call,
        )
    )
    raise MaxRetriesExceeded(DECISION_MAX_RETRIES, last_call.error)
