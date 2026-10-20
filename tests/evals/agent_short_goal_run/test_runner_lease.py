"""每个评测样本的世界租约都在离开 runner 前归还，包括异常路径。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.runner import one as runner
from pokemon_agent.schemas.harness.domain import RunResult


@pytest.mark.parametrize("fails", [False, True])
def test_runner_releases_the_world_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    sample = load_samples()[0]
    events: list[str] = []
    world = SimpleNamespace(release_lease=lambda: events.append("release"))
    monkeypatch.setattr(runner, "_load_env", lambda path: None)
    monkeypatch.setattr(runner, "prepare_archive", lambda sample, work: "manifest")
    monkeypatch.setattr(
        runner, "build_real", lambda **kwargs: (SimpleNamespace(deps="runtime"), world)
    )

    def restore(manifest: object, build_branch: object, sample_id: str) -> RunResult:
        assert build_branch("main") == "runtime"
        events.append("run")
        if fails:
            raise RuntimeError("run failed")
        return RunResult(run_id="r", sample_id=sample_id, branch="main")

    monkeypatch.setattr(runner, "restore_run", restore)

    runner.run_one(sample, tmp_path, {}, run_config_path="config.json")

    assert events == ["run", "release"]
    record = json.loads((tmp_path / "run.json").read_text("utf-8"))
    assert ("run failed" in record["error"]) == fails


def test_consecutive_samples_can_acquire_the_same_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned: list[str] = []
    samples = load_samples()[:2]
    monkeypatch.setattr(runner, "_load_env", lambda path: None)
    monkeypatch.setattr(runner, "prepare_archive", lambda sample, work: "manifest")

    def build(**kwargs: object) -> tuple[SimpleNamespace, SimpleNamespace]:
        assert not owned, "previous sample still holds the lease"
        owned.append(str(kwargs["run_id"]))
        return SimpleNamespace(deps="runtime"), SimpleNamespace(release_lease=owned.clear)

    def restore(manifest: object, build_branch: object, sample_id: str) -> RunResult:
        build_branch("main")
        return RunResult(run_id="r", sample_id=sample_id, branch="main")

    monkeypatch.setattr(runner, "build_real", build)
    monkeypatch.setattr(runner, "restore_run", restore)

    for index, sample in enumerate(samples):
        runner.run_one(sample, tmp_path / str(index), {}, run_config_path="config.json")
        assert not json.loads((tmp_path / str(index) / "run.json").read_text("utf-8"))["error"]

    assert not owned
