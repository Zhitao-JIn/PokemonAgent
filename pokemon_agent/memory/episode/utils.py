"""蒸馏跨局摘要时用的几个纯函数：把一局的单步记忆压成能进 prompt 的形状。

单独拎出来是因为它们不碰模型也不碰库，可以脱离 LLM 单测——
给一串 `StepMemory` 断言压出来的文本长什么样，不需要造假 provider。
"""

from __future__ import annotations

from typing import List, Dict, Any

from pokemon_agent.schemas.episode_memory import EpisodeMemory
from pokemon_agent.schemas.episode_summary_io import EpisodeMemoryContent, EpisodeStep
from pokemon_agent.schemas.step_memory import StepMemory


def _get_episode_memories(
    memory_entries: List[StepMemory],
    episode_id: str
) -> List[StepMemory]:
    """获取特定episode的所有基础（单步）记忆条目。"""
    return [m for m in memory_entries if m.episode_id == episode_id]


def _memory_entry_to_episode_steps(
    entries: List[StepMemory]
) -> List[EpisodeStep]:
    """把单步记忆（`StepMemory`）序列，整理成喂给蒸馏 prompt 的 `EpisodeStep` 序列。

    `StepMemory` 本身不含"场景"这个字段（它按位置检索，不按场景分类），
    这里用 `before.position` 兜底填 `scene`——蒸馏 prompt 只需要一个人可读的
    场景标识，不需要结构化的 `map_id`。

    把单步记忆整理成喂给蒸馏 prompt 的形状。
    """
    steps: List[EpisodeStep] = []
    for i, entry in enumerate(entries, 1):
        steps.append(EpisodeStep(
            thought="；".join(entry.rationale) or "无思考过程",
            action=entry.action,
            action_times=1,
            result_summary=entry.after.overview or "无结果",
            scene=entry.before.position or "unknown",
            step_number=i,
        ))
    return steps


def _create_episode_memory(
    episode_id: str,
    run_id: str,
    goal: str,
    outcome: Dict[str, Any],
    content: EpisodeMemoryContent,
    rationale: str,
    stamp: str,
) -> EpisodeMemory:
    """把 LLM 蒸馏出的 `EpisodeMemoryContent` 和这一局的元信息组装成一条 `EpisodeMemory`。

    前置条件：`outcome` 至少含 `success`（bool）与 `steps`（int）——
        由调用方（`EpisodeMemoryGenerator.generate_summary`）保证，
        这两个值来自 harness 对这一局的结算，不是这里要重新计算的东西。

    把蒸馏结果和这一局的元信息组装成一条摘要记忆。
    """
    return EpisodeMemory(
        episode_id=episode_id,
        run_id=run_id,
        goal=goal,
        success=bool(outcome.get("success", False)),
        steps=int(outcome.get("steps", 0)),
        content=content,
        rationale=rationale,
        stamp=stamp,
    )
