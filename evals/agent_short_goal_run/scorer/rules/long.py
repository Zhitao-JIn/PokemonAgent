"""长期开放探索任务的机械判据。"""

from __future__ import annotations

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
    failed,
    passed,
    target_frames,
    unjudgeable,
    with_ram,
)
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict


def _map_id(frame: Frame) -> int | None:
    """内存观测中的地图编号。"""
    return frame.content.facts.map_id


def _party_count(frame: Frame) -> int:
    """内存读数中的队伍人数。"""
    ram = frame.content.ram
    assert ram is not None
    return len(ram.party)


@rule("leave_pallet_town")
def leave_pallet_town(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """先拥有宝可梦，再到达北边地图 12；只读内存读数与账本帧。"""
    frames = with_ram(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有带内存读数的帧；地图 37、0、40、38 后的 0、队伍≥1、12 均未观测")
    if _map_id(frames[0]) != 38:
        return unjudgeable(
            f"起点地图不是 38；地图 37={_first_map(frames, 37)}、地图 0={_first_map(frames, 0)}、"
            f"地图 40={_first_map(frames, 40)}、地图 38 后的 0={_first_map_after_38(frames)}、"
            f"队伍≥1={_first_party(frames)}、地图 12={_first_map(frames, 12)}"
        )

    i_party = next((i for i, frame in enumerate(frames) if _party_count(frame) >= 1), None)
    i_map12 = next((i for i, frame in enumerate(frames) if _map_id(frame) == 12), None)
    milestones = (
        f"地图 37={_first_map(frames, 37)}、地图 0={_first_map(frames, 0)}、"
        f"地图 40={_first_map(frames, 40)}、地图 38 后的 0={_first_map_after_38(frames)}、"
        f"队伍≥1={i_party}、地图 12={i_map12}"
    )
    if i_party is None:
        return failed(f"从未拿到宝可梦；{milestones}", frames[0], frames[-1])
    later_map12 = next(
        (i for i in range(i_party + 1, len(frames)) if _map_id(frames[i]) == 12), None
    )
    if later_map12 is not None:
        return passed(
            f"取得宝可梦后到达地图 12；{milestones}", frames[i_party], frames[later_map12]
        )
    if i_map12 is not None and i_map12 < i_party:
        return failed(f"先到地图 12 再有宝可梦；{milestones}", frames[i_map12], frames[i_party])
    return failed(f"拿到了宝可梦但没到地图 12；{milestones}", frames[i_party], frames[-1])


def _first_map(frames: list[Frame], map_id: int) -> int | None:
    """首次出现指定地图的帧序号。"""
    return next((i for i, frame in enumerate(frames) if _map_id(frame) == map_id), None)


def _first_map_after_38(frames: list[Frame]) -> int | None:
    """首次出现地图 38 后又回到地图 0 的帧序号。"""
    first_38 = _first_map(frames, 38)
    if first_38 is None:
        return None
    return next((i for i in range(first_38 + 1, len(frames)) if _map_id(frames[i]) == 0), None)


def _first_party(frames: list[Frame]) -> int | None:
    """首次队伍人数至少一只的帧序号。"""
    return next((i for i, frame in enumerate(frames) if _party_count(frame) >= 1), None)


__all__ = ["leave_pallet_town"]
