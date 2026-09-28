"""感知过程集（spec §九②）：看档帧上视觉给的 `scene=battle` 与内存战斗标志逐帧对照。

`experiment/observation_check/` 的人工标注结论不在这里重算，报表只引用它。
"""

from __future__ import annotations

from evals.e2e.checks import RunStream
from evals.e2e.schemas import SenseAgreement
from pokemon_agent.world import Facts


def sense_agreement(stream: RunStream) -> SenseAgreement:
    """整个 run 里带内存读数、问过视觉的帧。"""
    frames = [f for f in stream.frames() if f.content.perceived and f.content.ram is not None]
    agree = sum(
        1
        for f in frames
        if (f.content.facts.scene is Facts.Scene.BATTLE) == f.content.ram.in_battle  # type: ignore[union-attr]
    )
    return SenseAgreement(frames=len(frames), agree=agree)


__all__ = ["sense_agreement"]
