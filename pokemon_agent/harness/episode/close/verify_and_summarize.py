"""`verify_and_summarize`：收尾链的最后一格（之后接 `close_episode`）。

**两跳、两个 LLM 调用**，对应 `Brain` 的 `verify` 与 `summarize` 两个方法：

1. **校验**：把本局全量 step 记忆（模型自述的 before/action/after，从没被验证过）
   交给独立判定器逐条判可信不可信。直接拿自述去蒸馏会把错误操作蒸馏成经验并
   跨局传播，所以这一步是必须的。
2. **蒸馏**：harness 自己拿 `verdicts` 筛出可信的那些（**"过滤归 harness"**——
   这样想怎么用就怎么用），只把可信的交给 `summarize()` 写跨局摘要并落库。

**这条链就是 episode memory 的定义**：它的**正文** = 本局通过校验的 step memory 的
蒸馏结果（派生物，可重建、可丢弃）；**来源章**由 `BrainTool.summarize()` 从 `req` 上
照抄 harness 的 run state。判据与三条推论见
`schemas/memory/datastore/episode_memory.py` 的类 docstring。

两跳的账分开记：校验记 `VERIFY_CALL`（含逐条 verdicts，报表按它解析失效率），
蒸馏记 `SUMMARIZE_CALL`——拆开之后校验器的 token 账不再混着写摘要那部分。
**账名（`verify_call` / `summarize_call`）本身已经说明是哪条链**，链路名只在
错误账（`CALL_EXHAUSTED` 的 `link`）上出现。

**失败语义（2026-09-13 取消降级）**：两跳都不再就近吞成"保守结果"。
`BrainTool.verify`/`BrainTool.summarize` 各自重试 `BRAIN_MAX_ATTEMPTS` 次仍失败时
抛 `MaxRetriesExceeded`，**本节点原样上抛**——"校验器整个失效"和"这一局的记忆确实
都不可信"在数据里必须分得开，前者是一条错误事件，后者是一份业务结论。
唯一保留的就近处理是**渲染 prompt 的 `KeyError`**（模板占位符对不上）：
那是编程错误，不是模型不配合，就近抛出去同样比吞掉好。

只在 `verify_step_entries` 非空时才会走到这一格（路由见 `episode/episode_graph.py`）
——为空时这一局的收尾链在上一格就结束了，不存在不经校验的全量蒸馏路径。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def _report_link_failed(
    deps: HarnessDeps,
    call_kind: TraceKind,
    link: str,
    ep: str,
    step: int,
    exc: MaxRetriesExceeded,
) -> None:
    """节点失败留痕：整条账落成 `MODEL_CALL` + 一条只说明"节点完了、为什么"的失败事件。

    0913 定案：**账与失败态分开记**。这里两笔都写（本节点是耗尽现场，
    是唯一拿得到 `exc.calls` 的地方），失败事件**不带账**——它的 `why`
    直接取 `exc.last_reason`。

    两个参数各管一头（0914）：`call_kind` 说这批调用账属于哪条链
    （`SUMMARIZE_CALL` / `VERIFY_CALL`，它就是账名），`link` 是**链路名的值**
    （`"summarize"` / `"verify"`），只落进 `CALL_EXHAUSTED` 的 `content.link`
    ——从前这里是第二个 `failed_kind`，五个 `*_FAILED` 成员合并成 `CALL_EXHAUSTED`
    之后由 `link` 顶替它承担"是哪条链出的错"。
    """
    source = "verify_and_summarize"
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            meta={"source": source, "episode_id": ep, "step": step},
            kind=call_kind,
            calls=list(exc.calls),
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CALL_EXHAUSTED,
            meta={"source": source, "episode_id": ep, "step": step},
            link=link,
        )
    )


def verify_and_summarize(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """逐条校验 step 记忆，只用可信的那些蒸馏摘要并落库。**只改 `verified_steps` 一处。**

    前置条件：`state.observation` 非空且 `state.done`、`state.verify_step_entries` 非空。
    后置条件：返回 `{"verified_steps": …}`。两跳中任一跳的重试预算耗尽都会抛
    `MaxRetriesExceeded`（`source` 分别是 `"verify"` 与 `"summarize"`），
    **本节点不接**——由图的调用方决定这一局的收场方式。
    """
    deps = runtime.context
    assert state.observation is not None and state.done, (
        "verify_and_summarize before the episode finished"
    )
    assert state.verify_step_entries, "verify_and_summarize 不该在没有 entries 时被路由到"
    ep, step = state.episode_id, state.observation.step
    obs = state.observation
    entries = state.verify_step_entries
    knowledge_text = "\n\n".join(state.verify_knowledge.contents) if state.verify_knowledge else ""

    # 步骤 1：校验。prompt **不在这里拼**（0913 定案）：本节点只装素材，
    # `BrainTool.verify()` 入口拼（`prompts.verify.build_prompt()`）。
    # 真正问模型那步（`deps.brain_tool.verify`）的 `MaxRetriesExceeded` 原样上抛。
    # 要带的截图同样由 `BrainTool.verify()` 对 entries 跑 `dedup_snapshots()` 取
    # （0915 130 收权）——本节点只装 entries 素材。
    verified = _verify(deps, ep, step, entries, knowledge_text, state.task.goal)

    # 步骤 2：蒸馏。**过滤在这一跳之前**——只把可信的记录交给 summarizer。
    # 一条可信的都没有时不往下走（prompt 里"至少有一步"的承诺在这里守住）。
    if not verified:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SUMMARY_PARSE_ERROR,
                meta={"source": "verify_and_summarize", "episode_id": ep, "step": step},
                reason="没有任何可信的 step 记忆，跳过蒸馏",
            )
        )
        return {"verified_steps": verified}

    mreq = FromHarnessToBrainToolSummarizeReq(
        entries=verified,
        episode_id=ep,
        run_id=deps.run_id,
        goal=state.task.goal,
        success=state.success,
        steps=obs.step,
        max_steps=state.task.max_steps,
    )
    # prompt 由 `BrainTool.summarize()` 入口拼（0913 定案）。

    try:
        result = deps.brain_tool.summarize(mreq)
    except MaxRetriesExceeded as exc:
        _report_link_failed(deps, TraceKind.SUMMARIZE_CALL, "summarize", ep, step, exc)
        raise

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_CALL,
            meta={"source": "verify_and_summarize", "episode_id": ep, "step": step},
            calls=result.calls,
        )
    )
    episode_memory = deps.memory.store_episode_summary(
        FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=result.episode_memory)
    ).memory

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_EPISODE,
            meta={"source": "verify_and_summarize", "episode_id": ep, "step": step},
            # 同一个 `kind` 有两个生产者：这条是**正文版**，`review` 那条是空章版。
            memory=episode_memory,
        )
    )

    return {"verified_steps": verified}


def _verify(
    deps: HarnessDeps,
    ep: str,
    step: int,
    entries: list,
    knowledge_text: str,
    goal: str,
) -> list:
    """跑校验这一跳，落两条 trace（调用账 + 汇总），返回**可信的 entries**。

    过滤在这里完成（"过滤归 harness"）：`verdicts.index` 落回 `entries` 下标，
    只保留 `reliable=True` 的那些——宁可少喂一条，也不把没依据的自述当验证过的
    结论喂给蒸馏。

    **不兜底**：`BrainTool.verify` 重试耗尽会抛 `MaxRetriesExceeded`，这里原样
    让它冒穿。"全部标不可信"那份保守结果不在这条路径上产生——它代表的是一个
    业务结论，而校验器坏掉是另一回事。

    **但逃出去之前要留痕**（0913 定案）：先落整条失败账（`MODEL_CALL`），
    再补一条只说明"节点完了、为什么"的 `VERIFY_FAILED`，然后原样上抛。
    """
    req = FromHarnessToBrainToolVerifyReq(
        entries=entries,
        goal=goal,
        knowledge=knowledge_text,
    )
    # prompt 由 `BrainTool.verify()` 入口拼（0913 定案）。
    try:
        result = deps.brain_tool.verify(req)
    except MaxRetriesExceeded as exc:
        _report_link_failed(deps, TraceKind.VERIFY_CALL, "verify", ep, step, exc)
        raise
    verdicts = result.verdicts
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_CALL,
            meta={"source": "verify_and_summarize", "episode_id": ep, "step": step},
            calls=result.calls,
            verdicts=verdicts,
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_VERDICT,
            meta={"source": "verify_and_summarize", "episode_id": ep, "step": step},
            checked=len(verdicts),
            unreliable=sum(1 for v in verdicts if not v.reliable),
            input=result.calls[-1].payload.get("prompt", ""),
            output=result.calls[-1].payload.get("raw", ""),
        )
    )

    reliable = {v.index for v in verdicts if v.reliable}
    return [e for i, e in enumerate(entries) if i in reliable]
