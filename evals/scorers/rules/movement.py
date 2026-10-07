"""移动与换图类判据：只看位置与地图编号（永远来自内存）。"""

from __future__ import annotations

from evals.schema.sample import EvalSample
from evals.scorers.registry import rule
from evals.scorers.stream import RunStream
from evals.scorers.utils import ends, failed, passed, target_frames, unjudgeable
from evals.scorers.verdict import CheckVerdict


@rule("map_changed")
def map_changed(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """末帧的地图编号与开局不同（走进门 / 进宝可梦中心）。"""
    pair = ends(target_frames(stream, sample))
    if pair is None:
        return unjudgeable("目标局里不足两帧")
    start, last = pair
    if last.content.facts.map_id != start.content.facts.map_id:
        return passed(
            f"地图 {start.content.facts.map_id} → {last.content.facts.map_id}", start, last
        )
    return failed(f"末帧仍在地图 {last.content.facts.map_id}", start, last)


@rule("reach_map12_y14")
def reach_map12_y14(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """末帧在地图 12 且 y ≥ 14（绕过正南的障碍）。"""
    pair = ends(target_frames(stream, sample))
    if pair is None or pair[1].content.place is None:
        return unjudgeable("目标局末帧没有位置")
    last = pair[1]
    place = last.content.place
    if place.map_id == 12 and place.y >= 14:
        return passed(f"末帧在地图 12 的 y={place.y}", last)
    return failed(f"末帧在地图 {place.map_id} 的 x={place.x} y={place.y}", last)


__all__ = ["map_changed", "reach_map12_y14"]
