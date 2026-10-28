"""冻结现场的可重现核验：无本机采集目录、无模型、无网络。"""

import copy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.dataset.brain_calls import load_references
from evals.dataset.brain_calls.dataset_contract import InputCase
from evals.dataset.brain_calls.independent_reference import (
    judge_reference,
    planning_reference,
    summary_reference,
)
from evals.dataset.brain_calls.scope_audit import verify_scope
from evals.dataset.brain_calls.source_archive import (
    SourceArchiveManifest,
    load_source_events,
    verify_sources,
)
from evals.dataset.brain_calls.verify_dataset import verify, verify_pair
from evals.dataset.brain_choose import load as load_choices
from evals.dataset.brain_judge import load as load_judges
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.memory import EpisodeMemory

ROOT = Path(__file__).resolve().parents[2] / "evals/dataset/brain_calls/v1"


def test_frozen_status_tampering_is_rejected_even_after_the_typed_field_is_removed() -> None:
    raw = json.loads((ROOT / "choose/inputs.jsonl").read_text("utf-8").splitlines()[0])
    row = InputCase.model_validate(raw)
    reference = load_references("choose")[0]
    altered = copy.deepcopy(raw["request"])
    altered["obs"]["status"] = "tampered frozen status"

    with pytest.raises(ValueError, match="typed input round trip changed request"):
        verify_pair(row, reference, verify_sources(ROOT), altered)


def cases(family: str) -> list[InputCase]:
    """读取提交的生产请求，不依赖 ignored 采集文件。"""
    return [
        InputCase.model_validate_json(line)
        for line in (ROOT / family / "inputs.jsonl").read_text("utf-8").splitlines()
    ]


def test_five_families_verify_from_the_frozen_source_archive() -> None:
    counts = verify(ROOT)

    assert set(counts) == {"judge", "plan", "decompose", "choose", "summary"}
    assert all(count > 0 for count in counts.values())


def test_native_versions_keep_three_judge_layers_and_legal_choice_labels() -> None:
    judges, choices = load_judges("v3"), load_choices("v2")

    assert {case.layer for case in judges} == {"run", "episode", "task"}
    assert all(case.evidence and case.truth_method == "mechanical" for case in judges)
    assert choices and all(case.label_source == "rule" for case in choices)
    assert all(
        case.request.space.enabled(matcher.key or matcher.script)
        for case in choices
        for matcher in case.acceptable
    )


def test_judge_reference_never_uses_observations_after_its_call() -> None:
    sample = next(row for row in load_samples() if row.sample_id == "knowledge_wild_encounter")
    events = load_source_events(ROOT, sample.sample_id)
    early = next(
        row
        for row in cases("judge")
        if row.source.sample_id == sample.sample_id and row.layer == "episode"
    )
    cutoff = next(
        index for index, event in enumerate(events) if event.uuid == early.source.trace_uuids[0]
    )

    full_reference = judge_reference(early, sample, events)
    prefix_reference = judge_reference(early, sample, events[: cutoff + 1])

    assert full_reference == prefix_reference
    assert full_reference.achieved is False


def test_open_references_never_read_collected_baseline_answers() -> None:
    samples = {sample.sample_id: sample for sample in load_samples()}
    for family in ("plan", "decompose", "summary"):
        case = cases(family)[0]
        changed = case.model_copy(
            update={
                "source": case.source.model_copy(update={"baseline_file": "does-not-exist.json"})
            }
        )
        if family == "summary":
            original, replacement = summary_reference(case), summary_reference(changed)
            assert original.constraints["source_records"] > 0
        else:
            original = planning_reference(case, samples[case.source.sample_id])
            replacement = planning_reference(changed, samples[case.source.sample_id])

        assert original == replacement
        assert replacement.achieved is None


def test_l1_background_uses_goal_identity_instead_of_goal_text() -> None:
    case = cases("decompose")[0]
    events = load_source_events(ROOT, case.source.sample_id)
    foreign = EpisodeMemory(
        run_id=case.source.meta["run_id"],
        goal_id="different-goal",
        episode_id="other-episode",
        goal=case.request.goal.goal,
        steps=1,
        summary="same words are not same identity",
        quality_score=0.5,
        quality_rationale="test",
    )
    changed = case.model_copy(
        update={"request": case.request.model_copy(update={"episode_index": [foreign]})}
    )

    with pytest.raises(ValueError, match="invalid L1 background"):
        verify_scope(changed, events)


def test_quantity_confirmation_uses_screen_instead_of_stale_item_options() -> None:
    sample = next(row for row in load_samples() if row.sample_id == "knowledge_shop_select_item")
    case = next(
        row
        for row in cases("judge")
        if row.source.sample_id == sample.sample_id and row.layer == "episode"
    )
    events = load_source_events(ROOT, sample.sample_id)

    reference = judge_reference(case, sample, events)

    assert reference.achieved is True
    assert reference.check_id == "visible_state.purchase_confirmation_screen"
    assert "×01" in case.request.observation.facts.screen


def test_catch_result_examples_are_not_treated_as_an_exhaustive_list() -> None:
    sample = next(row for row in load_samples() if row.sample_id == "knowledge_catch_throw_ball")
    case = next(
        row
        for row in cases("judge")
        if row.source.sample_id == sample.sample_id
        and row.layer == "episode"
        and row.request.observation
        and "Aww! It appeared to be caught!" in row.request.observation.facts.dialog_text
    )

    reference = judge_reference(case, sample, load_source_events(ROOT, sample.sample_id))

    assert reference.achieved is True
    assert reference.check_id == "visible_state.catch_result_text"


def test_judge_metrics_keep_layers_and_do_not_count_a_run_as_a_task() -> None:
    from evals.brain_judge.metrics import JudgeObservation, summarize

    observations = [
        JudgeObservation(True, True, "other", None, "run-id", "run-id", "run"),
        JudgeObservation(False, False, "other", "other", "task-id", "episode-id", "task"),
    ]

    metrics = summarize(observations)

    assert metrics["layer.run.n"] == metrics["layer.task.n"] == 1
    assert metrics["overall_unique_tasks"] == metrics["overall_unique_episodes"] == 1


def _source_event(kind: str, content: dict, seq: int) -> TraceEvent:
    """一条最小可落盘事件；meta 只带来源包要求的最小身份。"""
    return TraceEvent(
        uuid=f"0000000{seq}-0000-0000-0000-000000000000",
        seq=seq,
        kind=kind,
        type="memory_io" if kind.startswith("write_") else "brain_call",
        started_at=float(seq),
        ended_at=float(seq),
        meta=json.dumps({"run_id": "r1", "branch": "main"}),
        content=json.dumps(content, ensure_ascii=False),
    )


def test_source_archive_reader_parses_only_whitelisted_kinds(tmp_path: Path) -> None:
    """缺 index 的旧写账不参与解析；白名单内的账照常类型化。"""
    sample_id = "sample"
    legacy_run_memory = {
        "summary": "旧摘要",
        "reason": "旧结论",
        "reusable_patterns": [],
        "critical_decisions": [],
        "failure_points": [],
        "quality_score": 0.5,
        "quality_rationale": "旧评分",
        "applicable_scenes": [],
        "tags": [],
        "markdown": "旧正文",
    }
    events = [
        _source_event(
            "episode_start",
            {"goal_id": "g1", "goal": "走到门口", "success_criteria": "进屋", "max_steps": 3},
            1,
        ),
        _source_event("write_run_memory", legacy_run_memory, 2),
        _source_event("run_start", {"goals": ["总目标"], "success_criteria": ["通关"]}, 3),
        _source_event("judge_call", {"ok": True}, 4),
    ]
    archive = tmp_path / "sources.zip"
    entries = {}
    with ZipFile(archive, "w") as stream:
        for event in events:
            name = f"work/runs/{sample_id}/trace/{event.uuid}.json"
            data = event.model_dump_json().encode("utf-8")
            stream.writestr(name, data)
            entries[name] = hashlib.sha256(data).hexdigest()
    (tmp_path / "sources.manifest.json").write_text(
        SourceArchiveManifest(
            archive=archive.name,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            entries=entries,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    parsed = load_source_events(tmp_path, sample_id)

    assert [event.kind for event in parsed] == ["episode_start", "judge_call"]
    assert parsed[0].content.goal_id == "g1"
    assert parsed[1].content.ok is True
