"""`think_action` 与它的重试循环 `choose_with_retry` + 预算 `DECISION_MAX_RETRIES`。

**重试循环为什么在这里而不是在 Brain**：`choose_once()` 只负责单次尝试，"谁控制
循环，谁重试"——见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"。
循环直接 import `pokemon_agent.prompts.decide_action` 自己拼重试纠正说明：拼 prompt 是
harness 的事，`Brain` 只认现成的字符串（`choose_once(req)`），它不提供、也不该提供
`retry_prompt()` 这类方法。

**账不写在循环里**：`choose_with_retry` 只交回"每一次尝试的原始材料"（`ModelCallLog`）
与结局，落账由宿主节点做（本文件的 `think_action` 调 `deps.trace.append_model_calls`，
把账装成 `FromHarnessToTraceToolAppendModelCallsReq` 交上去）。
规则是"账写在它的宿主里"，取舍与代价见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4。

**同步调用**：无头模式下世界不限速（见 `pokemon_agent/world/pyboy_world.py`），决策等待
期间演化世界省不出时间——tick 本身就是瞬间的，异步 + 轮询反而是多余的复杂度。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, ActionSegment
from pokemon_agent.errors import DecisionAttemptFailed, MaxRetriesExceeded
from pokemon_agent.prompts import decide_action as decide_action_prompt
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    ModelCallLog,
)
from pokemon_agent.tools.interface import BrainToolPort
from pokemon_agent.trace import Source, TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState

DECISION_MAX_RETRIES = 3
"""决策重试预算：一次决策最多问几次模型。"""


def choose_with_retry(
    brain_tool: BrainToolPort,
    req: FromHarnessToBrainToolChooseOnceReq,
) -> tuple[Action | None, ModelCallLog]:
    """反复问一次决策，直到成功或预算耗尽——**循环与端口调用在这里**。

    `req.prompt` 是首次尝试用的基础 prompt（调用方已经拼好回填过）；重试时
    `req.model_copy(update={"prompt": ...})` 换掉这一个字段再传给 `choose_once(req)`，
    `req` 其余字段（`space` 等）原样带着，不用再传第二个参数。

    端口是**参数**、不是 `self` 属性——这样能用假端口独立测试，不用起一张真图。

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


def think_action(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """大脑推理，然后**把它交回来的账翻译成事件**。

    重试用尽（`action is None`）时本格补一条 `DECISION_FAILED` 再抛
    `MaxRetriesExceeded`（见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4）。

    前置条件：`state.observation`、`state.action_space` 非空。
    后置条件：返回 `{"plan": …, "pending_presses": …, "plan_step_start": …}`——
    链原文、展开后的逐键队列、以及这条链从第几步开始。
    """
    deps = runtime.context
    assert state.observation is not None, "think_action before record_observation"
    assert state.action_space is not None, "think_action without an action space"
    ep, step = state.episode_id, state.observation.step

    # 步骤 1：拼这一步的基础 prompt。knowledge/episode_memories 单独传，
    # 不折进 obs.facts（见 `retrieve/merge_retrieval.py` 的说明）——各自在
    # `decide_action.md` 里有独立占位符和可信度说明。
    knowledge_text = (
        "\n\n".join(state.knowledge_semantic_memory.contents)
        if state.knowledge_semantic_memory
        else ""
    )
    episode_memories_text = (
        "\n\n".join(m.render() for m in state.global_episode_memories)
        if state.global_episode_memories
        else ""
    )
    # 步骤 1.5：取一次人类实时插话（`RunDataCenter` 的 human_note 槽，取到即清空，
    # 只对这一次决策生效）。没接前端（`deps.data_center` 为 `None`）时恒为空串。
    # 取到非空才留痕——没人插话是常态，不该每步都记一条空事件。
    human_note = deps.data_center.take_human_note() if deps.data_center else ""
    if human_note:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.HUMAN_NOTE_INJECTED,
                episode_id=ep,
                step=step,
                text=human_note,
            )
        )

    req = FromHarnessToBrainToolChooseOnceReq(
        goals=state.episode_goals,
        obs=state.observation,
        space=state.action_space,
        memories=state.step_episode_memories,
        knowledge=knowledge_text,
        episode_memories=episode_memories_text,
        human_note=human_note,
    )
    # Harness 自己经 `pokemon_agent.prompts.decide_action` 拼 prompt，再把 prompt 回填进
    # 同一个 req——`req` 是 `build_prompt()` 和 `choose_once()` 共享的唯一输入，
    # 不必两套参数各传一遍。
    req = req.model_copy(update={"prompt": decide_action_prompt.build_prompt(req)})

    # 步骤 2：问一次决策（重试循环在 `choose_with_retry`；账由本格落——`log` 里失败与
    # 成功两种尝试都在，逐条进 MODEL_CALL）。
    action, log = choose_with_retry(deps.brain_tool, req)
    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            episode_id=ep, step=step, source=Source.DECISION, log=log
        )
    )

    # 步骤 2.5：预算耗尽——补一条 DECISION_FAILED（把最后一次失败的账带出来，报表按它
    # 统计失效率），再抛 `MaxRetriesExceeded`。本步到此为止。
    if action is None:
        last = log[-1][1]
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.DECISION_FAILED,
                episode_id=ep,
                step=step,
                call=last,
            )
        )
        raise MaxRetriesExceeded(DECISION_MAX_RETRIES, f"{last.error_kind}: {last.error}")

    # 步骤 3：写 THINK（记的是**整条链**），把链交回 state。`attempt` = 这条链是第几次
    # 尝试问出来的（就是 `log` 最后一条的序号）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.THINK,
            episode_id=ep,
            step=step,
            action=action,
            attempt=log[-1][0],
        )
    )

    # 步骤 4：把链展开成「一键一段」的待按队列——一次决策交出的东西在这一格定型，
    # `press/act` 只负责弹队首（把展开塞进 `act` 会让"这一次决策打算按什么"散在 N 圈里，
    # 链原文也就没有一处权威拷贝了）。
    #
    # 每段带着**它所属那一段**的 rationale：`times=4` 声明这 4 下同质，所以理由共享；
    # 展开后每一份都仍是"这一步为什么按"。`times` 只是书写压缩，展开成 N 个 `times=1`
    # 不改变任何语义。
    presses = [
        ActionSegment(name=segment.name, times=1, rationale=list(segment.rationale))
        for segment in action.sequence
        for _ in range(segment.times)
    ]
    # 顺带记下**这条链从第几步开始**（`plan_step_start`）：链内的键要能被认领回这一次
    # 决策（记忆侧按它分组，见 `schemas/memory/datastore/step_memory.py::render_decisions()`）。
    # 它是执行期的记账，`StepMemory` 那一份由 `store/step_episode_memory` 从这里抄。
    return {"plan": action, "pending_presses": presses, "plan_step_start": step}
