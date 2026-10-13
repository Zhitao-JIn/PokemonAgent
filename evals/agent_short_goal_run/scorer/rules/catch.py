"""捕捉类判据：对手 HP、背包里的精灵球（游戏变量）。"""

from __future__ import annotations

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
    POKE_BALL,
    ends,
    first_match,
    target_frames,
    unjudgeable,
)
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict


def _foe_hp(frame: Frame) -> int | None:
    """对手当前 HP；不在战斗时为 None。"""
    ram = frame.content.ram
    return ram.battle.foe.hp if ram is not None and ram.battle is not None else None


def _balls(frame: Frame) -> int:
    """背包里精灵球的数量。"""
    ram = frame.content.ram
    assert ram is not None
    return sum(item.quantity for item in ram.bag if item.item_id == POKE_BALL)


@rule("foe_hp_dropped")
def foe_hp_dropped(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """对手 HP 比开局低。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    if pair is None or _foe_hp(pair[0]) is None:
        return unjudgeable("开局不在战斗或帧不够")
    start_hp = _foe_hp(pair[0])
    assert start_hp is not None
    return first_match(
        frames,
        lambda f: (hp := _foe_hp(f)) is not None and hp < start_hp,
        found="对手 HP 降了",
        missing="对手 HP 没降",
    )


@rule("ball_thrown")
def ball_thrown(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """扔出了精灵球：背包里的精灵球比开局少。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    if pair is None:
        return unjudgeable("帧不够")
    start = _balls(pair[0])
    return first_match(
        [f for f in frames if f.content.ram is not None],
        lambda f: _balls(f) < start,
        found="精灵球少了一个",
        missing="精灵球数量没变",
    )


__all__ = ["ball_thrown", "foe_hp_dropped"]
