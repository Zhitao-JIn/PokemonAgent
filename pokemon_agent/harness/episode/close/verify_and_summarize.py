"""`verify_and_summarize`：拿 `verify_step_entries`/`verify_knowledge` 问独立判定器，
**一次调用**问完两件事：哪些 step 记忆可信、只用可信的那些蒸馏出跨局摘要并落库。
**图上单独一格，收尾链的最后一格**（之后接 `close_episode`）。

step 记忆是模型自述（`Brain.reflect()` 打包 before/action/after），没有验证——直接喂蒸馏
会把错误操作蒸馏成经验并跨局传播。独立判定器（`Brain.verify_and_summarize`，`verify_llm`
——可以配成跟 judge 不同的模型）在同一次输出里先逐条把关、再只用可信的写摘要；这次合并
调用的账仍记在 `Source.VERIFY` 下（校验器自己的失效率要说得出，代价是这条账单现在也混进
了写摘要那部分的 token，不再是纯校验成本）。

只在 `verify_step_entries` 非空时才会走到这一格（路由见 `episode/episode_graph.py`）
——为空时这一局的收尾链在上一格就结束了，不存在不经校验的全量蒸馏路径。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import StepVerifyVerdict
from pokemon_agent.prompts import verify_and_summarize as verify_and_summarize_prompt
from pokemon_agent.providers import ModelCall
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolVerifyAndSummarizeReq,
    FromHarnessToBrainToolVerifyAndSummarizeResp,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.schemas.memory import dedup_snapshots
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def verify_and_summarize(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """逐条校验 step 记忆，只用可信的那些蒸馏摘要并落库。**只改 `verified_steps` 一处。**

    前置条件：`state.observation` 非空且 `state.done`、`state.verify_step_entries` 非空。
    后置条件：返回 `{"verified_steps": …}`；摘要那一半失败时（`summary`/`episode_memory`
    为 None）只记一条 `EPISODE_SUMMARY_ERROR`，不影响本局结果。
    """
    deps = runtime.context
    assert state.observation is not None and state.done, (
        "verify_and_summarize before the episode finished"
    )
    assert state.verify_step_entries, "verify_and_summarize 不该在没有 entries 时被路由到"
    ep, step = state.episode_id, state.observation.step
    obs = state.observation
    entries = state.verify_step_entries
    knowledge_text = (
        "\n\n".join(state.verify_knowledge.contents) if state.verify_knowledge else ""
    )
    outcome: dict[str, Any] = {
        "success": state.success,
        "steps": obs.step,
        "max_steps": state.task.max_steps,
    }

    # 步骤 1：Harness 自己经 `pokemon_agent.prompts.verify_and_summarize` 拼 prompt、回填进
    # 同一个 req（同 `gate/judge` 的模式）：拼装本身可能抛的 KeyError 在这就近吞成"全部标
    # 不可靠 + 不写摘要"，不冒穿；真正问模型那步（`deps.brain_tool.verify_and_summarize`）
    # 异常原样上抛，两层各管各的失败原因，不要混在一起。
    #
    # 全量历史对应的截图（`StepMemory` 自带 base64，不用读盘），去重后一起交给校验器——跟
    # `judge` 同一套 `dedup_snapshots()`，区别只是这里没有"当前帧"要额外拼进来（校验的是
    # 已经结束的一局，没有正在进行的"当前"这一说），第二个返回值（对应的观测列表）这里也
    # 用不上——`build_prompt()` 转文字只靠 `entries` 本身（`render_sequence()`）。
    images, _ = dedup_snapshots(entries)
    # 多帧拼接不在调用方做——`ArkProvider._prepare_images` 在发送前自动把多帧打包成一张网格
    # 图（豆包按张计费且与分辨率无关，拼接是 provider 层的结构保证）。

    req = FromHarnessToBrainToolVerifyAndSummarizeReq(
        goal=state.task.goal,
        entries=entries,
        knowledge=knowledge_text,
        images=images,
        episode_id=ep,
        run_id=deps.run_id,
        success=outcome["success"],
        steps=outcome["steps"],
        max_steps=outcome["max_steps"],
    )
    try:
        req = req.model_copy(update={"prompt": verify_and_summarize_prompt.build_prompt(req)})
    except Exception as exc:  # noqa: BLE001  同 Brain.verify_and_summarize() 原有的取舍
        result = FromHarnessToBrainToolVerifyAndSummarizeResp(
            verdicts=[
                StepVerifyVerdict(
                    index=i, reliable=False, why=f"合并调用失败：{type(exc).__name__}"
                )
                for i in range(len(entries))
            ],
            summary=None,
            call=ModelCall(
                payload={"ok": "False", "attempt": "1"},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            ),
            why=f"合并调用失败：{type(exc).__name__}",
        )
    else:
        result = deps.brain_tool.verify_and_summarize(req)

    # 步骤 2：合并调用的账单（MODEL_CALL，VERIFY）——逐条 verdicts 由 tool 结构化进 payload
    # （报表按它解析失效率）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_CALL,
            episode_id=ep,
            step=step,
            call=result.call,
            verdicts=result.verdicts,
        )
    )
    # 逐条 verdicts 在 MODEL_CALL 里（报表按它解析失效率）；这里补轻量汇总给观测台链上
    # 这一格当内容。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_RESULT,
            episode_id=ep,
            step=step,
            checked=len(result.verdicts),
            unreliable=sum(1 for v in result.verdicts if not v.reliable),
        )
    )
    reliable = {v.index for v in result.verdicts if v.reliable}
    verified = [e for i, e in enumerate(entries) if i in reliable]

    # 摘要那一半解析/调用失败：只记一条错误，这一局不落跨局摘要，不影响本局结果。
    if result.summary is None or result.episode_memory is None:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_SUMMARY_ERROR,
                episode_id=ep,
                step=step,
                reason=result.why or "合并调用没能拿到 summary",
            )
        )
        return {"verified_steps": verified}

    episode_memory = deps.memory.store_episode_summary(
        FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=result.episode_memory)
    ).memory

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_MEMORY_WRITE,
            episode_id=ep,
            step=step,
            memory=episode_memory,
        )
    )

    return {"verified_steps": verified}
