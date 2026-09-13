"""`think_action`：大脑推理，然后**把它交回来的账翻译成事件**。

**重试循环不在这里了**——搬到 `BrainTool.choose()` 那一层。
理由：重试要拼重试纠正说明，而拼 prompt 是"谁问模型"的事——0913 定案后
**拼 prompt 整体归 `BrainTool`**（`tools.prompts` 那条渲染链的调用点唯一在
tool 入口），循环放它那儿不用跨层回传中间状态。harness 这格因此退化成
"组装素材 → 交一次 → 落账"，成功/失败的账都由 tool 打包好：
成功在 `resp.calls`，耗尽在抛出的 `MaxRetriesExceeded` 上（同样带整条账）。

**账不写在 tool 里**：`choose()` 只交回"每一次尝试的原始材料"与结局，
落账仍由宿主节点做（本文件调 `deps.trace.append_model_calls`）——规则是
"账写在它的宿主里"。

**同步调用**：无头模式下世界不限速（见 `pokemon_agent/world/pyboy_world.py`），决策等待
期间演化世界省不出时间——tick 本身就是瞬间的，异步 + 轮询反而是多余的复杂度。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, ActionSegment
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    ModelCallLog,
    TraceKind,
)
from pokemon_agent.trace import Source

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def think_action(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """大脑推理，然后**把它交回来的账翻译成事件**。

    重试用尽时 `BrainTool` 抛的 `MaxRetriesExceeded` 携带整条失败账——本格先把
    整条账逐条落成 `MODEL_CALL`，再补一条只说明"节点完了、为什么"的
    `DECISION_FAILED`，然后原样上抛（见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4）。

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
    # prompt **不在这里拼**（0913 定案）：本节点只装素材，拼 prompt 是
    # `BrainTool.choose()` 入口的事——"谁问模型，谁把 req 变成 prompt"，
    # 拼装只剩那一个调用点。

    # 步骤 2：问一次决策。重试循环在 `BrainTool.choose()` 里；成功的整条账
    # （失败尝试 + 最后一次成功）走 `resp.calls`，本格只负责落账。
    try:
        resp = deps.brain_tool.choose(req)
    except MaxRetriesExceeded as exc:
        # 步骤 2.5：预算耗尽——异常携带整条失败账。落账 + 补一条
        # DECISION_FAILED，再原样上抛。
        #
        # **两笔分开**（0913 定案）：账归 `append_model_calls`（整条链逐条落成
        # `MODEL_CALL`）；`DECISION_FAILED` 只回答"这个节点完了、为什么"，
        # 从异常取 `last_reason`，**不搬账**——以前传 `calls=[last]` 是为了让
        # 渲染拼出那句 `last:`，而它本来就挂在异常上。
        log: ModelCallLog = [(i, call) for i, call in enumerate(exc.calls, start=1)]
        deps.trace.append_model_calls(
            FromHarnessToTraceToolAppendModelCallsReq(
                episode_id=ep, step=step, source=Source.DECISION, log=log
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.DECISION_FAILED,
                episode_id=ep,
                step=step,
                why=exc.last_reason,
            )
        )
        raise

    log = [(i, call) for i, call in enumerate(resp.calls, start=1)]
    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            episode_id=ep, step=step, source=Source.DECISION, log=log
        )
    )
    action: Action = resp.action

    # 步骤 3：写 THINK（记的是**整条链**），把链交回 state。`attempt` = 这条链是第几次
    # 尝试问出来的（最后一次尝试的序号）。
    #
    # **规范化不留痕**（0913 删 `normalized`）：`_normalize()` 只把"连按 a"改成
    # "按一次"这类**等价改写**——改写后的动作就是 `action` 本身，trace 里那条链
    # 记的已经是规范化之后的。原动作不另存一份，因为没有任何消费者需要它。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.THINK,
            episode_id=ep,
            step=step,
            action=action,
            attempt=len(resp.calls),
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
