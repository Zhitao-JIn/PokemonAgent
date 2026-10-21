"""候选审计工具的独立测试：判据规则映射与执行坐标去重。"""

from __future__ import annotations

import pytest

from evals.dataset.brain_judge.build import check_id_for, dedupe
from evals.dataset.brain_judge.build.audit_candidates import Candidate


def _candidate(**overrides) -> Candidate:
    base = dict(
        event_uuid="u1",
        source_batch="task_capture_20261018_102238",
        source_choose_case="s/000001",
        run_id="r",
        episode_id="e",
        task_id="t",
        step=2,
        goal="g",
        criteria="c",
        goal_family="navigation",
        exact_request_and_image_match_verified=True,
        capture_version_limit="x",
        raw={},
    )
    return Candidate(**{**base, **overrides})


# --------------------------------------------------------------------------- #
# check_id_for：criteria → 已有机械规则
# --------------------------------------------------------------------------- #


def test_check_id_for_maps_known_criteria() -> None:
    assert check_id_for("map_id 不再是 0（已进入门后的地图）") == "map_changed"
    assert check_id_for("where 显示 map_id 仍是 12 且 y >= 14") == "reach_map12_y14"
    assert (
        check_id_for("光标显示在 RUN 上（选项仍为 FIGHT/PKMN/ITEM/RUN，场景仍为 battle）")
        == "cursor_on_run"
    )
    assert check_id_for("对话非空（overlay 为 dialog 且 dialog_text 非空）") == "dialog_opened"


def test_check_id_for_returns_none_for_unmapped_criteria() -> None:
    assert check_id_for("where 显示 x=12 y=5") is None
    assert check_id_for("光标在 ITEM 上（选项仍为 FIGHT/PKMN/ITEM/RUN）") is None


# --------------------------------------------------------------------------- #
# dedupe：按 (run, episode, task, step) 去重
# --------------------------------------------------------------------------- #


def test_dedupe_rejects_duplicate_coordinates() -> None:
    a = _candidate(event_uuid="u1")
    b = _candidate(event_uuid="u2")
    with pytest.raises(RuntimeError, match="重复"):
        dedupe([a, b])


def test_dedupe_keeps_distinct_steps() -> None:
    a = _candidate(event_uuid="u1", step=2)
    b = _candidate(event_uuid="u2", step=3)
    assert len(dedupe([a, b])) == 2
