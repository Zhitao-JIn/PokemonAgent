"""`retrieve_verify_knowledge` 与它的检索 query `build_verify_knowledge_query`。

整局一次检索领域知识，交给 `verify_and_summarize` 判领域合理性。**图上单独一格，只改
`verify_knowledge` 一处。**

只在 `verify_step_entries` 非空时才会走到这一格（路由见 `episode/episode_graph.py`）。
检索账单独记一条 `MEMORY_READ`——收尾路径没有 `merge_retrieval` 可以顺路记账，这里自己
记，否则 trace 看不出"校验器看到了什么知识"。

`build_verify_knowledge_query` 跟着本节点（判据见 `PLAN_graph_composition.md` §3.5）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.schemas.memory import StepMemory
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState
from ..retrieve.retrieve_knowledge_semantic_memory import MEMORY_RECALL_LIMIT


def build_verify_knowledge_query(entries: list[StepMemory], goal: str) -> str:
    """拼校验器的知识检索 query：整局 step 记忆的 scene/overlay/动作特征并集 + goal。

    跟 `retrieve/build_knowledge_query` 同一个教训——只按 goal 检索时战斗/菜单类先验在
    BM25 里匹配不上。校验器手里没有单一 observation（它审的是整局），所以这里取整局
    entries 的 before/after scene/overlay 加动作描述的并集，覆盖这一局实际经过的所有
    场景，而不是只覆盖终局那一帧。
    """
    scenes: set[str] = set()
    overlays: set[str] = set()
    actions: set[str] = set()
    for entry in entries:
        for obs in (entry.before, entry.after):
            if obs.facts.scene is not None:
                scenes.add(obs.facts.scene_value)
            if obs.facts.overlay is not None:
                overlays.add(obs.facts.overlay_value)
        actions.add(entry.action)
    bits = (
        [f"scene:{s}" for s in sorted(scenes)]
        + [f"overlay:{s}" for s in sorted(overlays)]
        + [f"action:{a}" for a in sorted(actions)]
    )
    return " ".join(bits + [f"目标：{goal}"])


def retrieve_verify_knowledge(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """整局一次领域知识检索。**只改 `verify_knowledge` 一处。**

    前置条件：`state.observation` 非空、`state.verify_step_entries` 非空（路由保证）。
    后置条件：返回 `{"verify_knowledge": …}`。
    """
    deps = runtime.context
    assert state.observation is not None, "retrieve_verify_knowledge before judge"
    ep, step = state.episode_id, state.observation.step
    knowledge_result = deps.memory.query_knowledge(
        FromHarnessToMemoryToolQueryKnowledgeReq(
            query=build_verify_knowledge_query(state.verify_step_entries, state.task.goal),
            limit=MEMORY_RECALL_LIMIT,
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.MEMORY_READ,
            episode_id=ep,
            step=step,
            memories=[],
            knowledge="\n\n".join(knowledge_result.contents),
            knowledge_sources=knowledge_result.sources,
            read_kind="read_verify_knowledge",
        )
    )
    return {"verify_knowledge": knowledge_result}
