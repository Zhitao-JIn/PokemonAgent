"""world_script_execute 与冻结帧采集共用的真实模拟器装配，不接视觉模型。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from evals.paths import REPO_ROOT
from pokemon_agent.world import PyBoyWorld, RamReadout, TaskObservation

ROM = REPO_ROOT / "assets" / "rom"


def start_world(state: Path, pre: Sequence[str], *, case_id: str) -> PyBoyWorld:
    """从调用方给定的完整存档路径起 world，并按完开跑前的键。

    前置条件：存档存在（缺了 `PyBoyWorld` 构造时当场炸——基础设施故障，交 inspect 记
    sample error，不进分母）。
    后置条件：返回的 world 已 reset，调用方用完负责 `stop()`。
    """
    world = PyBoyWorld(str(ROM), state_path=str(state))
    world.reset(task_id=case_id, goal="world 用例测评", success_criteria="-", max_steps=1)
    for key in pre:
        world.step([(key, 1)], settle=True)
    return world


def read_frame(world: PyBoyWorld) -> tuple[TaskObservation, RamReadout]:
    """读一帧 task 档观测与内存读数（不调模型）。

    后置条件：内存读数非空（task 档感知恒读内存）。
    """
    perceived = world.perceive_task()
    assert perceived.ram is not None, "task 档感知必带内存读数"
    return perceived.observation, perceived.ram


def stop_world(world: PyBoyWorld) -> None:
    """关闭测评模拟器，不把 SRAM 写回共享 ROM 路径；每例都从冻结存档重起。"""
    world._pyboy.stop(save=False)


__all__ = ["ROM", "read_frame", "start_world"]
