"""rubric ③ 少走冗余路（code grader）：按键数、重复访问同格次数、无效按键数。

v1 只算原始量、不折档（`score=None`）：0 / 1 / 2 档阈值要在第一批数据上标定后冻结进 rubric 版本
（`docs/eval/plan.md` E9）。
"""

from __future__ import annotations

from evals.e2e.checks import RunStream
from evals.e2e.schemas import EvalSample, RubricScore
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace.content import CheckStallContent

ITEM_ID = "redundant_path"


def score_redundant_path(stream: RunStream, sample: EvalSample) -> RubricScore:
    """算原始量。

    `revisits` = 位置序列里回到此前到过的格的次数；`stalled_keys` = 停摆计数为正的按键。
    """
    episodes = stream.episodes_for(sample.sample_id)
    presses = len(stream.in_episodes(episodes, TraceKind.PRESS_KEY))
    stalled = sum(
        1
        for e in stream.in_episodes(episodes, TraceKind.CHECK_STALL)
        if isinstance(e.content, CheckStallContent) and e.content.stall_count > 0
    )
    seen: set[tuple[int, int, int]] = set()
    revisits = 0
    last: tuple[int, int, int] | None = None
    for frame in stream.frames(episodes):
        place = frame.content.place
        if place is None:
            continue
        cell = (place.map_id, place.x, place.y)
        if cell == last:
            continue
        if cell in seen:
            revisits += 1
        seen.add(cell)
        last = cell
    return RubricScore(
        item_id=ITEM_ID,
        grader="code",
        score=None,
        detail={"presses": presses, "revisits": revisits, "stalled_keys": stalled},
    )


__all__ = ["ITEM_ID", "score_redundant_path"]
