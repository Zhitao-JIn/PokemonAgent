"""`perceive` 格（task 层）：取一帧、吸收上一键的后果，再给这一键备好动作空间。

    sense → detect_stall → store_step_episode_memory → store_object_semantic_memory
        → close_step → retrieve_act_memories → get_action_space

`sense` 每圈都取帧（RAM 档，task 层唯一取帧处）；首圈取到的就是这个 task 的开局帧。
中间三个单元只在上一圈按过键（`action` 非空）时干活。顺序是契约：两个 store 要
before/after 同时在场，所以转正（`close_step`）排在它们之后；查本 task 的 ActMemory
排在写之后，刚写的那条也读得到。
判定、决策、收尾都只用这里装好的 `task_ctx`，不再自己查库。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..task_runtime import TaskRuntime
from ..task_state import TaskState
from .close_step import close_step
from .detect_stall import detect_stall
from .get_action_space import get_action_space
from .retrieve_act_memories import retrieve_act_memories
from .sense import sense
from .store_object_semantic_memory import store_object_semantic_memory
from .store_step_episode_memory import store_step_episode_memory

_UNITS = (
    sense,
    detect_stall,
    store_step_episode_memory,
    store_object_semantic_memory,
    close_step,
    retrieve_act_memories,
    get_action_space,
)


def perceive(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """按序跑七个单元，返回全部增量的合并。"""
    # 步骤 1：取帧 → 吸收上一键 → 转正 → 读记忆 → 动作空间（顺序是契约）。
    return compose_units(state, runtime, _UNITS)


__all__ = ["perceive"]
