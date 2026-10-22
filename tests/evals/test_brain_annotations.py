"""历史标注只依赖当前请求，并与原始冻结输入逐条绑定。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.dataset.brain_annotations.contract import Annotation, Evidence
from evals.dataset.brain_annotations.evidence import proof
from evals.dataset.brain_annotations.loader import load
from evals.dataset.errors import DatasetError


def test_excluded_case_cannot_carry_a_gold_answer() -> None:
    evidence = Evidence(pointer="/goal", sha256="0" * 64, excerpt="goal")

    with pytest.raises(ValidationError, match="status/family/answer"):
        Annotation(
            case_id="case",
            family="judge",
            request_sha256="0" * 64,
            status="unjudgeable",
            method="codex_history_review",
            rationale="缺少证据",
            evidence=[evidence],
            achieved=False,
        )


def test_evidence_hash_changes_with_historical_input() -> None:
    before = {"history": [{"after": {"hp": "15/15"}}]}
    after = {"history": [{"after": {"hp": "10/15"}}]}

    first = proof(before, "/history/0/after/hp")
    second = proof(after, "/history/0/after/hp")

    assert first.excerpt == '"15/15"'
    assert first.sha256 != second.sha256


@pytest.mark.parametrize(
    ("family", "total", "labelled"),
    [("choose", 207, 131), ("judge", 289, 289), ("plan", 26, 25), ("decompose", 37, 36)],
)
def test_every_captured_request_has_verified_review_coverage(
    family: str, total: int, labelled: int
) -> None:
    rows = load(family)

    assert len(rows) == total
    assert sum(row.status == "labelled" for row in rows) == labelled
    assert all(row.evidence and row.rationale for row in rows)


def test_all_four_independent_versions_use_the_labelled_denominators() -> None:
    from evals.brain_decompose.dataset import load as decomposition
    from evals.brain_plan.dataset import load as planning
    from evals.dataset.brain_choose import load as choose
    from evals.dataset.brain_judge import load as judge

    assert len(choose("v3")) == 131
    assert len(judge("v4")) == 289
    assert len(planning("v2")) == 25
    assert len(decomposition("v2")) == 36
    assert planning("v2")[0].reference.label_source == "history_adjudicated"


def test_wrong_menu_quantity_and_partial_throw_result_remain_negative() -> None:
    rows = {row.case_id: row for row in load("judge")}

    assert rows["knowledge_battle_run_attempt.task.judge.000001"].achieved is False
    assert rows["knowledge_battle_run_attempt.task.judge.000002"].achieved is True
    assert rows["knowledge_shop_cancel_purchase.task.judge.000008"].achieved is False
    assert rows["knowledge_shop_cancel_purchase.task.judge.000010"].achieved is True
    assert rows["knowledge_catch_throw_ball.task.judge.000011"].achieved is False
    assert rows["knowledge_catch_throw_ball.task.judge.000012"].achieved is True


def test_planning_review_respects_the_visible_goal_identity() -> None:
    rows = {row.case_id: row for row in load("decompose")}
    original = rows["knowledge_battle_action_menu.episode.decompose.000002"]
    encounter = rows["knowledge_battle_action_menu.episode.decompose.000003"]

    assert original.status == "invalid_task"
    assert encounter.status == "labelled"
    assert "不跨 L1" in encounter.criteria[1].instruction
    assert (
        "无旧 TaskMemory"
        in rows["knowledge_shop_interaction.episode.decompose.000003"].criteria[0].instruction
    )


def test_repeated_keys_cannot_exploit_a_single_step_gold_label() -> None:
    from evals.brain_choose.compare import matches
    from evals.dataset.brain_choose.schemas import ActionMatcher
    from pokemon_agent.brain.interface import Action

    one = Action.model_validate({"sequence": [{"name": "a", "times": 1}]})
    repeated = Action.model_validate(
        {"sequence": [{"name": "a", "times": 1}, {"name": "a", "times": 1}]}
    )
    label = [ActionMatcher(key="a", max_times=1, max_total_times=1)]

    assert matches(one, label)
    assert not matches(repeated, label)


def test_changed_request_evidence_is_rejected_even_with_updated_file_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    import evals.dataset.brain_annotations.loader as loader

    source = loader.ROOT / "v1"
    directory = tmp_path / "v1"
    directory.mkdir()
    rows = (source / "choose.jsonl").read_text("utf-8").splitlines()
    first = json.loads(rows[0])
    first["evidence"][0]["sha256"] = "0" * 64
    rows[0] = json.dumps(first, ensure_ascii=False)
    path = directory / "choose.jsonl"
    path.write_text("\n".join(rows) + "\n", "utf-8")
    manifest = json.loads((source / "manifest.json").read_text("utf-8"))
    manifest["families"]["choose"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    monkeypatch.setattr(loader, "ROOT", tmp_path)

    with pytest.raises(DatasetError, match="evidence mismatch"):
        loader.load("choose")
