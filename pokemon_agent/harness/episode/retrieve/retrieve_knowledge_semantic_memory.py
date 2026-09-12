"""`retrieve_knowledge_semantic_memory` 与它的检索 query `build_knowledge_query`。

知识库（BM25 检索）需要一条 query 字符串，而**只按 goal 检索是不够的**：
战斗/菜单类先验（2×2 行动菜单、a 确认 b 取消）在 BM25 里匹配不上——agent 在战斗里
全靠猜，犯过"down×3 当 RUN""用 b 当确认"这类错（knowledge 里都有，就是没被检索到）。
所以 query 拼的是"这一帧观测的特征 + goal"，见 `build_knowledge_query`。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.trace import TraceKind
from pokemon_agent.world import Observation

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState

MEMORY_RECALL_LIMIT = 5
"""每次知识库检索取几条。

**两个读者**（本节点与 `close/retrieve_verify_knowledge`），所以它是本域里唯一一个
读者跨域的常量：住这里的理由是它按语义属于"知识库召回上限"，而收尾那次检索是同一件
事在收尾路径上的落地——两者共用一个数字，改一处就够（`PLAN_graph_composition.md`
§3.5 的归位判据在这条上是"两个服务者"，取更靠前的那个当宿主）。
"""


def build_knowledge_query(obs: Observation, goal: str) -> str:
    """拼知识库检索 query：observation 特征 + goal，不只按 goal 检索。"""
    bits = [
        f"scene:{obs.facts.scene_value}",
        f"overlay:{obs.facts.overlay_value}",
        obs.status,
    ]
    if obs.place is not None:
        bits.append(f"map:{obs.place.map_id}")
    return " ".join(filter(None, bits + [f"目标：{goal}"]))


def retrieve_knowledge_semantic_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """查领域知识库。**只改 `knowledge_semantic_memory` 一处。**

    前置条件：`state.observation` 非空。
    后置条件：返回 `{"knowledge_semantic_memory": …}`（整个 `QueryKnowledgeResp`，
    `contents` 与 `sources` 都要留给 `decide/think_action` 与记账）。
    """
    deps = runtime.context
    assert state.observation is not None, "retrieve_knowledge_semantic_memory before judge"
    obs, ep, step = state.observation, state.episode_id, state.observation.step
    result = deps.memory.query_knowledge(
        FromHarnessToMemoryToolQueryKnowledgeReq(
            query=build_knowledge_query(obs, state.task.goal),
            limit=MEMORY_RECALL_LIMIT,
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RETRIEVE_NODE,
            episode_id=ep,
            step=step,
            read_kind="knowledge",
            count=len(result.contents),
            refs=" ".join(result.sources),
        )
    )
    return {"knowledge_semantic_memory": result}
