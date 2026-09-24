"""`retrieve_knowledge_semantic_memory` 与它的检索 query `build_knowledge_query`。

知识库（BM25 检索）需要一条 query 字符串，而**只按 goal 检索是不够的**：
战斗/菜单类先验（2×2 行动菜单、a 确认 b 取消）在 BM25 里匹配不上——agent 在战斗里
全靠猜，犯过"down×3 当 RUN""用 b 当确认"这类错（knowledge 里都有，就是没被检索到）。
所以 query 拼的是"这一帧观测的特征 + goal"，见 `build_knowledge_query`。
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
from pokemon_agent.world import Observation

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


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
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """查领域知识库。**只改 `ep_ctx` 里知识那三个字段。**

    不是每圈都查：本局首圈、场景变了（野外 / 室内 / 战斗）、上次检索之后有 task 失败，
    这三种情况才重查并记 `read_knowledge`；其余圈沿用上次的结果，不查也不记账。

    前置条件：`state.ep_ctx` 非空。
    后置条件：重查时返回更新后的 `ep_ctx`（整个 `QueryKnowledgeResp`，`contents` 与
    `sources` 都要留给 `plan_episode` 与记账，外加这次检索时的场景与已结算 task 数）；
    沿用时返回空增量。
    """
    if not _needs_refresh(state):
        return {}
    deps = runtime.context
    obs, ep, step = state.ep_ctx.observation, state.episode_id, state.ep_ctx.observation.step
    query = build_knowledge_query(obs, state.goal.goal)
    result = deps.memory.query_knowledge(
        FromHarnessToMemoryToolQueryKnowledgeReq(
            query=query,
            limit=MEMORY_RECALL_LIMIT,
        )
    )
    # `refs` 列的是 `sources`（命中记录的文件名）——`contents` 与 `sources` 由
    # `memory_tool.query_knowledge` 在同一个循环里成对 append、**恒等长**，
    # 所以"命中几条"就是 `refs` 的长度，不必再单记一个数（0914 跟进）。
    # 收尾链那条 `read_verify_knowledge` 与这里同口径。
    # `query` 记**送给 BM25 的那串原文**（不是等值条件，它本来就带空格）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_KNOWLEDGE,
            meta={
                "source": "retrieve_knowledge_semantic_memory",
                "episode_id": ep,
                "task_id": ep,
                "step": step,
            },
            query=query,
            refs=list(result.sources),
        )
    )
    return {
        "ep_ctx": state.ep_ctx.model_copy(
            update={
                "knowledge_semantic_memory": result,
                "knowledge_scene": obs.facts.scene_value,
                "knowledge_at_tasks": len(state.task_outputs),
            }
        )
    }


def _needs_refresh(state: EpisodeRunState) -> bool:
    """这一圈要不要重查知识：本局还没查过、场景变了、上次检索之后有 task 失败，三者任一。"""
    ctx = state.ep_ctx
    if ctx.knowledge_semantic_memory is None:
        return True
    if ctx.observation.facts.scene_value != ctx.knowledge_scene:
        return True
    return any(not out.success for out in state.task_outputs[ctx.knowledge_at_tasks :])
