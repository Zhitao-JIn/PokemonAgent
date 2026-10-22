"""动作空间只传 world 的能力数据，展示文案归 prompt 版本。"""

from __future__ import annotations

from pokemon_agent.world import ActionSpace, TaskObservation
from pokemon_agent.world.action_space import compute_action_space


def action_space_for(obs: TaskObservation, all_actions: list[str]) -> ActionSpace:
    """依本帧计算能力掩码与原始条目，不装配模型文字。"""
    return compute_action_space(obs, all_actions)
