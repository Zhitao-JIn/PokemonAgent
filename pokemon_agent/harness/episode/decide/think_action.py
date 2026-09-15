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

**这里也是"act 位置"的插话点**（0914 控制台改造）：`act` 节点自己**没有** LLM 调用
（它只是弹 `pending_presses` 的队首），决策的产物 `Action` 是在**这一格**产生并展开
的。所以人若对"要按的这条链"有意见，插话只能落在这里的出口——**一条链要么整条重出，
要么就照原样跑完**，不存在"按了两个键再改后面那几个"（要改就得从决策这一格重来）。

插话的循环也住在这里：`Reviewer.inject()` 拿到一句话，就带着它**重问一次**
`BrainTool.choose()`，直到人没意见（空串）为止。**次数不设上限**（用户定调）。
人的那句话拼在 prompt **最末尾**（见 `tools/prompts/decide_action.py` 的
`_render_human_note`）——它是一条临时覆盖指令，压过上面所有规则。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import ActionSegment
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def think_action(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """大脑推理 → 人的插话 → 把最后采纳的那条链展开成待按队列。

    重试用尽时 `BrainTool` 抛的 `MaxRetriesExceeded` 携带整条失败账——本格先把
    整条账逐条落成 `MODEL_CALL`，再补一条只说明"节点完了、为什么"的
    `CALL_EXHAUSTED`（`link="decide"`），然后原样上抛——**账写在它的宿主格
    里**，成功走返回值，耗尽走异常。

    插话循环的代价：**每被插一次话就多一次完整的 `choose()` 调用**（重试预算
    也重来一遍）。这是用户明确接受的——人不会闲着没事每步插话。

    前置条件：`state.observation`、`state.action_space` 非空。
    后置条件：返回 `{"plan": …, "pending_presses": …}`——链原文与展开后的逐键队列。
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

    # 步骤 2：问决策 → 亮给人（插话）→ 人若说了什么就带着它重问。**循环不设上限**。
    human_note = ""
    while True:
        resp = _choose(deps, state, knowledge_text, episode_memories_text, human_note, ep, step)
        note = deps.reviewer.inject(
            FromHarnessToReviewerInjectReq(
                prompt=f"请审这条链（第 {step} 步，{len(resp.action.sequence)} 段）",
                form=resp.action,
                form_kind="Action",
            )
        )
        if not note:
            break
        human_note = note

    # 步骤 3：写 THINK（记的是**整条链**，附带那次成功的请求与原文），把链交回 state。
    #
    # **规范化不留痕**（0913 删 `normalized`）：`_normalize()` 只把"连按 a"改成
    # "按一次"这类**等价改写**——改写后的动作就是 `action` 本身，trace 里那条链
    # 记的已经是规范化之后的。原动作不另存一份，因为没有任何消费者需要它。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.THINK,
            meta={"source": "think_action", "episode_id": ep, "step": step},
            # 封套上的 `source` = 发这条账的节点名（`kind` 只说"哪本账"）。
            action=resp.action,
            input=resp.calls[-1].payload.get("prompt", ""),
            output=resp.calls[-1].payload.get("raw", ""),
            human_note=human_note,
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
        for segment in resp.action.sequence
        for _ in range(segment.times)
    ]
    return {"plan": resp.action, "pending_presses": presses}


def _choose(
    deps: HarnessDeps,
    state: EpisodeRunState,
    knowledge_text: str,
    episode_memories_text: str,
    human_note: str,
    ep: str,
    step: int,
) -> FromHarnessToBrainToolChooseOnceResp:
    """问一次决策、落这一次的账，返回 choose 的整份 resp（动作 + 整条账）。

    `human_note` 非空时它就进 req，由 `decide_action.build_prompt()` 渲染到
    prompt 的**最末尾**。

    失败路径：`MaxRetriesExceeded` 的整条账先落成 `MODEL_CALL`、再补一条
    `CALL_EXHAUSTED`（`link="decide"`），然后原样上抛——**插话循环不吞它**，
    人说的话救不了一次调不通的模型。
    """
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
    try:
        resp = deps.brain_tool.choose(req)
    except MaxRetriesExceeded as exc:
        # 预算耗尽——异常携带整条失败账。落账 + 补一条 CALL_EXHAUSTED，再原样上抛。
        #
        # **两笔分开**（0913 定案）：账归 `append_model_calls`（整条链逐条落成
        # `MODEL_CALL`）；`CALL_EXHAUSTED` 只回答"这个节点完了、为什么"，
        # 从异常取 `last_reason`，**不搬账**。
        log = list(exc.calls)
        deps.trace.append_model_calls(
            FromHarnessToTraceToolAppendModelCallsReq(
                meta={"source": "think_action", "episode_id": ep, "step": step},
                kind=TraceKind.DECIDE_CALL,
                log=log,
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED,
                meta={"source": "think_action", "episode_id": ep, "step": step},
                link="decide",
            )
        )
        raise

    log = list(resp.calls)
    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            meta={"source": "think_action", "episode_id": ep, "step": step},
            kind=TraceKind.DECIDE_CALL,
            log=log,
        )
    )
    return resp


__all__ = ["think_action"]
