"""判据共用的取帧与出结论的小工具（只服务 `checks/`）。

真值来源（spec §二）：`ram`（游戏变量）永远可信；对话 / 选项 / 光标只认 `ram.decoded`
（`Frame.text`），不认 `facts` 里的（episode 层那份来自视觉）；位置与地图（`place` /
`facts.map_id`）永远来自内存。
"""

from __future__ import annotations

from collections.abc import Callable

from evals.dataset.agent_short_goal_run.schemas import EvalSample
from evals.scorers.verdict import CheckVerdict

from .stream import Frame, RunStream

BATTLE_MENU: frozenset[str] = frozenset({"FIGHT", "PKMN", "ITEM", "RUN"})
"""战斗行动菜单的四项。"""

POKE_BALL = 0x04
"""精灵球的物品 ID。"""


def target_frames(stream: RunStream, sample: EvalSample) -> list[Frame]:
    """派给样本目标的那几局里的全部帧。"""
    return stream.frames(stream.episodes_for(sample.sample_id))


def with_ram(frames: list[Frame]) -> list[Frame]:
    """带内存读数的帧。"""
    return [f for f in frames if f.content.ram is not None]


def decoded(frames: list[Frame]) -> list[Frame]:
    """带屏幕解码文字的帧（有内存读数即有）。"""
    return [f for f in frames if f.from_decode]


def passed(reason: str, *frames: Frame) -> CheckVerdict:
    """判成。"""
    return CheckVerdict(outcome="pass", evidence=[f.uuid for f in frames], reason=reason)


def failed(reason: str, *frames: Frame) -> CheckVerdict:
    """判负。"""
    return CheckVerdict(outcome="fail", evidence=[f.uuid for f in frames], reason=reason)


def unjudgeable(reason: str) -> CheckVerdict:
    """这条样本的账不够判。"""
    return CheckVerdict(outcome="unjudgeable", reason=reason)


def first_match(
    frames: list[Frame], hit: Callable[[Frame], bool], *, found: str, missing: str
) -> CheckVerdict:
    """事件型判据：任一帧满足即判成，证据是第一帧命中的帧。"""
    for frame in frames:
        if hit(frame):
            return passed(found, frame)
    return failed(missing, *frames[-1:])


def ends(frames: list[Frame]) -> tuple[Frame, Frame] | None:
    """带内存读数的首帧与末帧（状态型判据与"比开局变了没有"用）；不足两帧为 None。"""
    usable = with_ram(frames)
    if len(usable) < 2:
        return None
    return usable[0], usable[-1]


__all__ = [
    "BATTLE_MENU",
    "POKE_BALL",
    "decoded",
    "ends",
    "failed",
    "first_match",
    "passed",
    "target_frames",
    "unjudgeable",
    "with_ram",
]
