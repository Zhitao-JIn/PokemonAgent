"""补采只执行所选用例；清单固定后按集合验收，不能只核条数。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from _harness_fixtures.harness import GOAL, build_fake

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.common.brain_capture import record_brain_calls
from evals.common.capture_audit import audit_capture
from evals.common.capture_batch import CaseReport, PackReport
from evals.common.capture_control import launch
from evals.common.capture_integrity import audit_batch
from evals.common.capture_selection import selected_samples
from evals.common.capture_state import read_state, save_state
from evals.common.invocation import write_record


@pytest.mark.parametrize("selection", [[], ["unknown"], ["unknown", "unknown"]])
def test_invalid_selection_is_rejected_before_creating_an_output(
    tmp_path: Path,
    selection: list[str],
) -> None:
    directory = tmp_path / "batch"

    with pytest.raises(ValueError):
        launch(directory, sample_ids=selection)

    assert not directory.exists()


def test_complement_selects_only_the_six_unfinished_cases_in_dataset_order() -> None:
    samples = load_samples("v20261021_retest5")
    completed = {sample.sample_id for sample in samples[:14]}
    remaining = [sample.sample_id for sample in samples if sample.sample_id not in completed]

    selected = selected_samples(list(reversed(remaining)))

    assert [sample.sample_id for sample in selected] == remaining
    assert len(selected) == 6
    assert not completed.intersection(sample.sample_id for sample in selected)


def test_resume_preserves_the_selected_subset_and_rejects_a_new_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import evals.common.capture_control as control

    monkeypatch.setattr(control, "start_process", lambda *args: SimpleNamespace(pid=123))
    ids = [sample.sample_id for sample in load_samples("v20261021_retest5")[-6:]]
    state = launch(tmp_path / "batch", sample_ids=ids)
    state.status = "failed"
    save_state(tmp_path / "batch", state)

    launch(tmp_path / "batch", resume=True)

    assert read_state(tmp_path / "batch").sample_ids == ids
    with pytest.raises(ValueError, match="cannot change"):
        launch(tmp_path / "batch", resume=True, sample_ids=ids[:1])


def test_a_subset_audit_requires_exactly_the_fixed_source_cases(tmp_path: Path) -> None:
    ids = [sample.sample_id for sample in load_samples("v20261021_retest5")[-2:]]
    pack = PackReport(
        git_head="fixed",
        schema_hash="schema",
        configuration_sha256="config",
        code_sha256="code",
        source_hashes={sample_id: "source" for sample_id in ids},
        archive_hashes={},
    )
    write_record(tmp_path / "pack_report.json", pack)
    (tmp_path / "reports").mkdir()
    for sample_id in ids:
        work = tmp_path / "runs" / sample_id
        fake = build_fake(work)
        record_brain_calls(fake.run_rt, work / "brain_calls")
        result = fake.harness.run("r1", [GOAL])
        report = CaseReport(
            sample_id=sample_id,
            git_head="fixed",
            exit_code=0,
            run_result=result,
            work_directory=str(work),
            audit=audit_capture(work),
        )
        write_record(tmp_path / "reports" / f"{sample_id}.json", report)

    assert audit_batch(tmp_path).completed == 2

    (tmp_path / "reports" / f"{ids[0]}.json").rename(tmp_path / "reports/unexpected.json")
    with pytest.raises(ValueError, match="every selected"):
        audit_batch(tmp_path)
