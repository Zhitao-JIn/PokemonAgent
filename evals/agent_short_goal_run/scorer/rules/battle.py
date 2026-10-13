"""战斗类判据：在不在战斗、双方 HP 看游戏变量；菜单走到哪看解码出的选项与光标。"""

from __future__ import annotations

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
    BATTLE_MENU,
    decoded,
    ends,
    first_match,
    target_frames,
    unjudgeable,
    with_ram,
)
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict

_MOVE_RESULT_TEXT: tuple[str, ...] = (" used ", "fainted", "failed", "Critical hit", "effective")
"""招式打出去之后对话框里会出现的字样。"""


def _in_battle(frame: Frame) -> bool:
    """这一帧在战斗中（内存战斗标志）。"""
    return frame.content.ram is not None and frame.content.ram.in_battle


def _foe_hp(frame: Frame) -> int | None:
    """对手当前 HP；不在战斗时为 None。"""
    ram = frame.content.ram
    return ram.battle.foe.hp if ram is not None and ram.battle is not None else None


@rule("battle_started")
def battle_started(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """进了战斗（内存战斗标志）。"""
    frames = with_ram(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有带内存读数的帧")
    return first_match(frames, _in_battle, found="进了战斗", missing="始终没进战斗")


@rule("cursor_on_run")
def cursor_on_run(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """战斗中光标停在 RUN。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")
    return first_match(
        frames,
        lambda f: _in_battle(f) and f.text.cursor == "RUN",
        found="光标到了 RUN",
        missing="光标从没停在 RUN",
    )


@rule("move_list_opened")
def move_list_opened(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """战斗中打开了招式列表：选项不是行动菜单四项，也不带 CANCEL（那是背包）。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")

    def is_moves(f: Frame) -> bool:
        options = set(f.text.options)
        return (
            _in_battle(f)
            and bool(options)
            and not options & BATTLE_MENU
            and "CANCEL" not in options
        )

    return first_match(frames, is_moves, found="打开了招式列表", missing="没打开招式列表")


@rule("move_used")
def move_used(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """招式打出去了：对手 HP 比开局低，或对话框出现招式结算字样。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    if pair is None or _foe_hp(pair[0]) is None:
        return unjudgeable("开局不在战斗或帧不够")
    start_hp = _foe_hp(pair[0])
    assert start_hp is not None

    def used(f: Frame) -> bool:
        hp = _foe_hp(f)
        if hp is not None and hp < start_hp:
            return True
        return f.from_decode and any(s in f.text.dialog_text for s in _MOVE_RESULT_TEXT)

    return first_match(frames, used, found="招式打出去了", missing="对手 HP 没降，也没出现结算字样")


@rule("bag_opened_in_battle")
def bag_opened_in_battle(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """战斗中打开了道具袋：选项带 CANCEL、且不是行动菜单。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")
    return first_match(
        frames,
        lambda f: (
            _in_battle(f) and "CANCEL" in f.text.options and not set(f.text.options) & BATTLE_MENU
        ),
        found="打开了道具袋",
        missing="没打开道具袋",
    )


@rule("run_attempted")
def run_attempted(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """逃跑有了结果：离开了战斗，或对话框出现 escape 字样（成功或失败都算）。"""
    frames = target_frames(stream, sample)
    usable = with_ram(frames)
    if not usable or not _in_battle(usable[0]):
        return unjudgeable("开局不在战斗")
    return first_match(
        usable,
        lambda f: not _in_battle(f) or (f.from_decode and "escape" in f.text.dialog_text),
        found="逃跑有了结果",
        missing="始终在战斗里，也没出现逃跑结果",
    )


__all__ = [
    "bag_opened_in_battle",
    "battle_started",
    "cursor_on_run",
    "move_list_opened",
    "move_used",
    "run_attempted",
]
