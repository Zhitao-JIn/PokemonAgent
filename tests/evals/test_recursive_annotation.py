"""递归规划批次的作者表与旁账：展示未登记失败关闭、排除项不携带答案、决策标签自洽。"""

import json

import pytest
from pydantic import ValidationError

from evals.dataset.brain_annotations import authoring
from evals.dataset.brain_annotations.contract import Annotation, Evidence
from evals.dataset.brain_annotations.loader import load
from evals.dataset.errors import DatasetError

VERSION = "v20261020_1846"
EVIDENCE = Evidence(pointer="/goal", sha256="0" * 64, excerpt="x")


def judge_row(**extra: object) -> Annotation:
    """最小 judge 标注，供决策标签规则示范。"""
    fields: dict[str, object] = {
        "case_id": "c",
        "family": "judge",
        "request_sha256": "1" * 64,
        "status": "labelled",
        "method": "codex_history_review",
        "rationale": "r",
        "evidence": [EVIDENCE],
    }
    return Annotation(**{**fields, **extra})


def test_expected_decision_must_agree_with_achieved() -> None:
    judge_row(achieved=True, expected_decision="achieved")

    with pytest.raises(ValidationError):
        judge_row(achieved=False, expected_decision="achieved")


def test_expected_decision_is_judge_only() -> None:
    with pytest.raises(ValidationError):
        Annotation(
            case_id="c",
            family="choose",
            request_sha256="1" * 64,
            status="labelled",
            method="codex_history_review",
            evaluation_mode="advisory",
            rationale="r",
            evidence=[EVIDENCE],
            criteria=[],
            expected_decision="continue",
        )


def test_authoring_rejects_missing_unknown_and_duplicate_rows(tmp_path, monkeypatch) -> None:
    table = tmp_path / "v" / "plan.jsonl"
    table.parent.mkdir()
    monkeypatch.setattr(authoring, "ROOT", tmp_path)
    row = {"case_id": "a", "status": "labelled", "rationale": "ok"}

    table.write_text(json.dumps(row) + "\n")
    with pytest.raises(DatasetError, match="misses"):
        authoring.load_authoring("v", "plan", ["a", "b"])

    with pytest.raises(DatasetError, match="unknown"):
        authoring.load_authoring("v", "plan", ["b"])

    table.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(DatasetError, match="duplicate"):
        authoring.load_authoring("v", "plan", ["a"])


def test_excluded_authoring_row_cannot_carry_an_answer(tmp_path, monkeypatch) -> None:
    table = tmp_path / "v" / "judge.jsonl"
    table.parent.mkdir()
    monkeypatch.setattr(authoring, "ROOT", tmp_path)
    table.write_text(
        json.dumps({"case_id": "a", "status": "unjudgeable", "rationale": "r", "achieved": True})
        + "\n"
    )

    with pytest.raises(DatasetError, match="carries an answer"):
        authoring.load_authoring("v", "judge", ["a"])


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_published_recursive_annotations_cover_every_case() -> None:
    counts = {
        family: len(load(family, VERSION)) for family in ("choose", "judge", "plan", "decompose")
    }

    assert counts == {"choose": 122, "judge": 183, "plan": 21, "decompose": 41}
    decisions = {row.expected_decision for row in load("judge", VERSION)}
    assert {"achieved", "continue", None} <= decisions
