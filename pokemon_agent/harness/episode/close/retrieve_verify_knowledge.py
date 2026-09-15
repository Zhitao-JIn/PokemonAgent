"""`retrieve_verify_knowledge` 与它的检索 query `build_verify_knowledge_query`。

整局一次检索领域知识，交给 `verify_and_summarize` 判领域合理性。**图上单独一格，只改
`verify_knowledge` 一处。**

只在 `verify_step_entries` 非空时才会走到这一格（路由见 `episode/episode_graph.py`）。
检索账自己记一条 `read_verify_knowledge`——收尾路径没有 `merge_retrieval` 可以顺路
记账，这里自己记，否则 trace 看不出"校验器看到了什么知识"。
**形状与主循环那条 `read_knowledge` 逐字相同**（0914 对齐审计前它借合并读的渲染，
多带 `step_memory_count` 等一堆跟自己无关的字段）。

`build_verify_knowledge_query` 跟着本节点。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import MEMORY_RECALL_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import StepMemory

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


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
    query = build_verify_knowledge_query(state.verify_step_entries, state.task.goal)
    knowledge_result = deps.memory.query_knowledge(
        FromHarnessToMemoryToolQueryKnowledgeReq(
            query=query,
            limit=MEMORY_RECALL_LIMIT,
        )
    )
    # `refs` 与主循环那条 `read_knowledge` 同口径：列命中记录的 `sources`。
    # `contents` 与 `sources` 由 `memory_tool` 在同一个循环里成对产出、恒等长，
    # 所以"命中几条"就是 `refs` 的长度，不必再单记一个数（0914 跟进；此前那个
    # `count` 号称"数一份、列另一份才构成交叉校验"，但两份本就是同一份的两列）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_VERIFY_KNOWLEDGE,
            meta={"source": "retrieve_verify_knowledge", "episode_id": ep, "step": step},
            query=query,
            refs=list(knowledge_result.sources),
        )
    )
    return {"verify_knowledge": knowledge_result}
