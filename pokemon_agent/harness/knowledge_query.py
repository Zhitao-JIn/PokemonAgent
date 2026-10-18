"""run 与 episode 共用的知识检索 query 拼装。"""

from __future__ import annotations

from pokemon_agent.world import TaskObservation


def build_knowledge_query(obs: TaskObservation, goal: str) -> str:
    """拼知识库检索 query：observation 特征 + goal，不只按 goal 检索。"""
    bits = [
        f"scene:{obs.scene.value}",
        f"overlay:{obs.facts.overlay_value}",
        obs.status,
    ]
    if obs.place is not None:
        bits.append(f"map:{obs.place.map_id}")
    return " ".join(filter(None, bits + [f"目标：{goal}"]))
