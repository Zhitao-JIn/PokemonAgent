"""宝可梦中心类判据：队伍 HP（游戏变量）。进中心用 `movement.map_changed`。"""

from __future__ import annotations

from evals.dataset.agent_goal_run.schemas import EvalSample
from evals.scorers.registry import rule
from evals.scorers.stream import Frame, RunStream
from evals.scorers.utils import first_match, target_frames, unjudgeable, with_ram
from evals.scorers.verdict import CheckVerdict


def _all_healed(frame: Frame) -> bool:
    """队伍每只 HP 都等于最大 HP。"""
    ram = frame.content.ram
    return ram is not None and bool(ram.party) and all(m.hp == m.max_hp for m in ram.party)


@rule("party_healed")
def party_healed(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """队伍被治好：开局有人受伤，之后某一帧每只 HP 都满。"""
    frames = with_ram(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有带内存读数的帧")
    if _all_healed(frames[0]):
        return unjudgeable("开局队伍本来就是满血，判不出治没治")
    return first_match(frames, _all_healed, found="队伍 HP 全满", missing="队伍始终有人没满血")


__all__ = ["party_healed"]
