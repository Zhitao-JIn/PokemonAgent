"""`EpisodeHarness` 与大脑交互专用的工具函数。

**只放这一根依赖会用到的重试循环**——跟 `game_utils.py`/`memory_query_utils.py` 是同一个
原则在 harness 各根依赖上各自的落地：互不依赖，谁的循环谁重试。

**账不在这里写。** 本模块只交回"每一次尝试的原始材料"（`ModelCallLog`）与结局，
落账由宿主做（`EpisodeHarness.think_action` 调 `trace_write.append_model_calls`）。
规则是"账写在它的宿主里"，取舍与代价见
`docs/spec/harness/PLAN_graph_readability.md` §3.7.4。

依赖注入的编排函数（`choose_with_retry` 调 `BrainToolPort`）：端口是**参数**、不是
`self` 属性——调用方（`EpisodeHarness` 的节点方法）传自己的 `self._brain` 进来，
这里就能用假端口独立测试，不用起一个真的 `EpisodeHarness`。
`choose_with_retry` 不碰 `GameToolPort`：决策是同步调用，不需要在等待期间演化世界。

**`choose_with_retry` 直接 import `pokemon_agent.prompts.decide_action` 自己拼重试
纠正说明**：拼 prompt 是 Harness 的事，`Brain` 只认现成的字符串
（`choose_once(req, prompt)`）——`Brain` 不提供、也不该提供 `retry_prompt()` 这类方法，
那会让它重新知道 prompt 内容怎么来。
"""

from __future__ import annotations

from pokemon_agent.brain import ActionFromBrain
from pokemon_agent.errors import DecisionAttemptFailed
from pokemon_agent.prompts import decide_action as decide_action_prompt
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.tools.interface import BrainToolPort

from .trace_write import ModelCallLog

DECISION_MAX_RETRIES = 3
"""决策重试预算：一次决策最多问几次模型。重试循环在这里（不在 Brain）——
"谁控制循环，谁重试"，见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"。"""


def choose_with_retry(
    brain_tool: BrainToolPort,
    req: FromHarnessToBrainToolChooseOnceReq,
) -> tuple[ActionFromBrain | None, ModelCallLog]:
    """反复问一次决策，直到成功或预算耗尽——**循环与端口调用在这里**，
    `choose_once()` 只负责单次尝试（见 `docs/ROADMAP.md`）。

    `req.prompt` 是首次尝试用的基础 prompt（调用方已经拼好回填过）；重试时
    `req.model_copy(update={"prompt": ...})` 换掉这一个字段再传给
    `choose_once(req)`，`req` 其余字段（`space` 等）原样带着，不用再传
    第二个参数。

    **同步调用**：无头模式下世界不限速（见
    `pokemon_agent/world/pyboy_world.py`），决策等待期间演化世界省不出时间
    ——tick 本身就是瞬间的，异步 + 轮询 `future.done()` 反而是多余的复杂度。
    直接同步调 `choose_once()`，拿到结果（或异常）就往下走。

    步骤 1：问一次，把这次的账收进 `log`，失败就带纠正提示进入下一次尝试。
    步骤 2：成功返回 `(动作, log)`。
    步骤 3：预算耗尽返回 `(None, log)`——**收场归调用方**（补一条 `DECISION_FAILED`
    事件、抛 `MaxRetriesExceeded`），因为那两件事都是记账，账要由宿主写。
    """
    base_prompt = req.prompt
    log: ModelCallLog = []
    for attempt in range(1, DECISION_MAX_RETRIES + 1):
        # 步骤 1：问一次，把账收进 log；失败就带纠正提示重试。
        try:
            resp = brain_tool.choose_once(req)
        except DecisionAttemptFailed as exc:
            call = exc.call
            log.append((attempt, call))
            retry_req = decide_action_prompt.RetryPromptReq(
                base_prompt=base_prompt,
                attempt=attempt + 1,
                reason=call.error,
                raw=call.payload.get("raw", "")[:400],
            )
            req = req.model_copy(update={"prompt": decide_action_prompt.retry_prompt(retry_req)})
            continue

        log.append((attempt, resp.calls[0]))
        return resp.action, log

    # 步骤 3：预算耗尽——材料交回调用方，由它决定怎么收场。
    return None, log
