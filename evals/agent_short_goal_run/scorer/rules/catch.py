"""捕捉类判据：对手 HP 与屏幕解码出的投球结果。"""

from __future__ import annotations

import re

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
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


def _ball_result(frame: Frame) -> bool:
    """只认实际解码的捕捉结算，不以道具光标或尚未结算的球数代替结果。"""
    if not frame.from_decode:
        return False
    text = " ".join(frame.text.dialog_text.casefold().split())
    return bool(
        re.search(r"all right!.*was caught|\bwas caught!|(?:darn!|oh no!).*broke free", text)
        or any(
            phrase in text
            for phrase in (
                "aww! it appeared to be caught",
                "aargh! almost had it",
                "shoot! it was so close",
            )
        )
    )


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
    """本次投球出现明确结果；球数可能在结果文字后扣除，不参与成功判据。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    if pair is None:
        return unjudgeable("帧不够")
    if _ball_result(pair[0]):
        return unjudgeable("开局已有捕捉结果，无法归因到本次投球")
    return first_match(
        frames,
        _ball_result,
        found="出现了投球结果文字",
        missing="未出现明确的投球结果文字",
    )


__all__ = ["ball_thrown", "foe_hp_dropped"]
