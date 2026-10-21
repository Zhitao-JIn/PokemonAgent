"""CP2 候选核对与真值审阅草稿工具的用法与不变量。

数据相关测试依赖两批已恢复的采集产物；缺失时跳过（不掩盖故障，也兼容无数据环境）。
"""

from __future__ import annotations

import pytest

from evals.dataset.brain_judge.build import check_id_for, dedupe, reconstruct, truth_for
from evals.dataset.brain_judge.build.audit_candidates import (
    _SOURCE_ROOT,
    Candidate,
    load_candidates,
)

_SOURCE_PRESENT = (_SOURCE_ROOT / "task_capture_20261018_102238").exists() and (
    _SOURCE_ROOT / "supplement_20261018_172952"
).exists()

requires_sources = pytest.mark.skipif(
    not _SOURCE_PRESENT, reason="两批采集产物未恢复，跳过数据相关用例"
)


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


# --------------------------------------------------------------------------- #
# 重建与核对（依赖采集产物）
# --------------------------------------------------------------------------- #


@requires_sources
def test_all_257_candidates_reconstruct_prompt_and_bind_images() -> None:
    candidates = dedupe(load_candidates())
    assert len(candidates) == 257
    for c in candidates:
        rec = reconstruct(c)
        assert rec.prompt_exact, f"{c.event_uuid} prompt 重建不一致"
        assert rec.image_bound, f"{c.event_uuid} 图片帧绑定不一致"
        assert len(rec.request_sha256) == 64


@requires_sources
def test_reconstruction_preserves_full_history_not_a_single_frame() -> None:
    candidates = dedupe(load_candidates())
    for c in candidates:
        rec = reconstruct(c)
        assert len(rec.history) == c.raw["history_entries_at_request"]
        # 每条 ActMemory 都带 before/after 两份完整观测（不缩成单帧）。
        for entry in rec.history:
            assert entry.before.facts.where or entry.before.status
            assert entry.after.facts.where or entry.after.status


@requires_sources
def test_truth_is_mechanical_for_mapped_criteria() -> None:
    candidates = dedupe(load_candidates())
    door = next(c for c in candidates if "map_id 不再是 0" in c.criteria)
    truth = truth_for(reconstruct(door))
    assert truth.method == "mechanical"
    assert truth.check_id == "map_changed"
    assert truth.achieved is not None
    assert truth.evidence and all("locator" in e for e in truth.evidence)


@requires_sources
def test_non_mechanical_position_criteria_is_only_a_suggestion_not_truth() -> None:
    candidates = dedupe(load_candidates())
    walk = next(c for c in candidates if c.criteria == "where 显示 x=14 y=8")
    truth = truth_for(reconstruct(walk))
    # 非机械样本不自动赋真值：achieved/method 为空，只给未审定建议。
    assert truth.method is None
    assert truth.achieved is None
    assert truth.suggested_achieved is True
    assert truth.suggested_negative_mode is None


@requires_sources
def test_ambiguous_disjunctive_criteria_has_no_suggestion() -> None:
    candidates = dedupe(load_candidates())
    ambiguous = next(c for c in candidates if "或与柜台后的人相邻" in c.criteria)
    truth = truth_for(reconstruct(ambiguous))
    assert truth.method is None
    assert truth.achieved is None
    assert truth.suggested_achieved is None


@requires_sources
def test_draft_record_preserves_full_history_frames() -> None:
    from evals.dataset.brain_judge.build.audit_candidates import _draft_record

    candidates = dedupe(load_candidates())
    rec = reconstruct(candidates[0])
    truth = truth_for(rec)
    draft = _draft_record(rec, truth)
    assert draft["request"]["history"]
    for entry in draft["request"]["history"]:
        assert entry.get("before_frame", "").startswith("data:image/png;base64,")
        assert entry.get("after_frame", "").startswith("data:image/png;base64,")


@requires_sources
def test_mechanical_evidence_locators_point_to_trace_files() -> None:
    candidates = dedupe(load_candidates())
    door = next(c for c in candidates if "map_id 不再是 0" in c.criteria)
    truth = truth_for(reconstruct(door))
    assert truth.method == "mechanical"
    assert all(e["source"] == "trace" for e in truth.evidence)
    assert all(".json" in e["locator"] for e in truth.evidence)
