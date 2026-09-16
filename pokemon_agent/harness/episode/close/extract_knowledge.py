"""`extract_knowledge`：收尾链的第四格——从这一局的**可信记录**里读出世界知识，
落进 `knowledge_memory`（0914 S4，`docs/PLAN_planner_v2.md` §3.6）。

# ⚠ 已摘出运行路径（0914 98）——本模块现在**不在图上**

用户 0914 定「knowledge 由人管理」：`knowledge_memory/` 那些先验由人写，
run 不再自动往里抽。所以 `episode_graph.py` 里没有这个节点，
`verify_and_summarize` 直接接 `close_episode`。

**代码与账大半原样留着**：本模块、`Brain.extract()` 第七链路、
`prompts/calls/extract.md`、`MemoryTool.store_knowledge()`、
`extract_call` / `call_exhausted`（`link="extract"`）两个 kind、
`tests/test_extract_knowledge.py` 全在原位。**例外是 `write_knowledge` 那本账——
0914 跟进整账删除**（knowledge 由人管理，根本没有计划走"模型写知识"这条路）：
`TraceKind` 成员、渲染器、req 上的 `records` 槽都没了；落库那半
（`store_knowledge`）照旧。
**接回去要动五处**，逐字形状见 `CHANGELOG.md` 第 98 条：
图里三行（import / `add_node` / 把直边换回条件边）、`node_io.py` 的六个节点表、
`check_harness` 的两条核对。

⚠ **唯一悬空物**：`state.verified_steps` 现在只有写方、没有读方——
它是本模块的输入面，接回去就重新有主了；要长期不用就该把它也摘掉。

**它和 `verify_and_summarize` 吃同一份素材、问两个问题**：

| | 问什么 | 产物属于谁 | 落哪个家族 |
|---|---|---|---|
| `verify_and_summarize` | 这一局打得怎么样 | 那一局 | `episode_memory/` |
| `extract_knowledge` | 这个世界有什么新事实 | 世界 | `knowledge_memory/` |

"属于那一局"的字面含义：`episode_id` 是它的**身份**。"属于世界"则是：
`run_id`/`episode_id` 只是**来源**（追溯用），这条知识以后会在别的 run 里被检索到。

这就是"对话与招式目前没有 memory 出口"那个缺口的补法：在此之前，一局跑完只留下
"这局怎么样"，画面里读到的规则（护士会治全队、商店怎么买）**一局结束后就没了**。

**为什么是一格而不是并进上一格**：两个产物、两条链路、两笔账，各自的失败
语义也不一样（见下）。并进 `verify_and_summarize` 会让"蒸馏坏了"和"抽取坏了"
在同一格里分不开——而那两件事的处置方式正好相反。

**它的失败不让这一局失败**（与 `verify`/`summarize` **刻意相反**）：

- `verify`/`summarize` 的产物是**这一局的记录本体**——拿不到就真的没有记录，
  所以它们重试耗尽时原样上抛，这一局以错误收场（那条错误事件就是它的墓碑）；
- 知识是**附加产物**：这一局的成败、步数、摘要都已经写好落库了，少学一条世界知识
  是**可接受的降级**——下一个局、下一次交互还会再读到它。为它把整局翻成
  `episode_error`，等于让一条"锦上添花"的链路有能力污染这个项目唯一的一组硬数字
  （成功率）。

所以这里的 `except` 是**唯一保留的就近处理**，而且它不是吞——`extract_call`
（整条账）+ `call_exhausted`（失败态）两笔都照写。"抽取失败了"与"这一局什么
都没读到"在 trace 上因此**分得开**：前者有一条 `error` 事件，后者没有。

**进来之前一定是非空的**：路由在 `verify_and_summarize` 出口按
`verified_steps` 分叉（`episode_graph.py`）——没有一条可信记录时直接跳
`close_episode`，不存在"拿未验证的自述去抽知识"的路径。从没被核对过的自述里
抽知识，等于把幻觉固化成"世界规则"。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolExtractReq,
    FromHarnessToMemoryToolStoreKnowledgeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def extract_knowledge(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """抽取本局的世界知识并落库。**不改 state 的任何字段**——它插在收尾链的
    末尾，产出全部落在记忆库与 trace 上。

    前置条件：`state.observation` 非空且 `state.done`；`state.verified_steps`
        非空（路由保证——空表示"没有可信记录"，那一支直接跳 `close_episode`）。
    后置条件：返回 `{}`。**任何失败都不上抛**：`BrainTool.extract` 重试耗尽时
        落两笔账（整条账 + 失败态）后原地收场，这一局照常去 `close_episode`。
    """
    deps = runtime.context
    assert state.observation is not None and state.done, (
        "extract_knowledge before the episode finished"
    )
    assert state.verified_steps, "extract_knowledge 不该在没有可信记录时被路由到"

    ep, step = state.episode_id, state.observation.step
    entries = state.verified_steps
    # 只装素材（0915 130 收权）：要带的截图由 `BrainTool.extract()` 对同一批
    # entries 跑 `dedup_snapshots()` 取——与校验/蒸馏同源，prompt 由 tool 入口拼
    # （同其余五条链路）。
    req = FromHarnessToBrainToolExtractReq(
        entries=entries,
        episode_id=ep,
        run_id=deps.run_id,
        goal=state.task.goal,
    )

    try:
        result = deps.brain_tool.extract(req)
    except MaxRetriesExceeded as exc:
        _report_link_failed(deps, ep, step, exc)
        return {}

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EXTRACT_CALL,
            meta={"source": "extract_knowledge", "episode_id": ep, "step": step},
            calls=result.calls,
        )
    )

    # **零条不落库**：这是最常见的结果；"抽取白跑了没"由上面那条账单回答。
    if not result.records:
        return {}

    # 落库照旧（记忆侧的事）；**trace 这边不再有写账**（0914 跟进删
    # `write_knowledge` 这本账——knowledge 由人管理，根本没有计划走
    # "模型写知识"这条路）。判重可能把交回来的一批全吃掉，库的增量看库里。
    deps.memory.store_knowledge(FromHarnessToMemoryToolStoreKnowledgeReq(records=result.records))
    return {}


def _report_link_failed(deps: HarnessDeps, ep: str, step: int, exc: MaxRetriesExceeded) -> None:
    """抽取失败留痕：整条账落成 `MODEL_CALL` + 一条只说明"这一格完了、为什么"的失败事件。

    **与 `verify_and_summarize._report_link_failed` 逐字同形，但刻意不共用**：
    两处的差别只在**逃出去之后**（那边 `raise`、这里 `return {}`），而"重试耗尽
    了该不该把这一局带走"正是这两个节点各自的核心决定——共用一个 helper 会把
    两件**变更触发条件不同**的事绑在一起（改一边的逃逸行为要动另一边读的代码）。
    跟 `tools/trace/__init__.py` docstring 里"合包不合并"是同一条判据。

    两笔的分工见那份 docstring：`EXTRACT_CALL` 记账（"花了多少钱"），
    `CALL_EXHAUSTED`（`link="extract"`）记失败态（"这一格放弃了"），后者**不带账**
    ——账在上面那笔里。
    """
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            meta={"source": "extract_knowledge", "episode_id": ep, "step": step},
            kind=TraceKind.EXTRACT_CALL,
            calls=list(exc.calls),
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CALL_EXHAUSTED,
            meta={"source": "extract_knowledge", "episode_id": ep, "step": step},
            link="extract",
            why=exc.last_reason,
        )
    )


__all__ = ["extract_knowledge"]
