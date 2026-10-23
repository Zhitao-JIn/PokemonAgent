"""单样本 run 直接加载原始状态，并在所有退出路径释放世界租约。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.runner import one as runner


@pytest.mark.parametrize("failure", [None, RuntimeError])
def test_runner_releases_world_after_success_or_run_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception] | None
) -> None:
    sample = load_samples()[0]
    events: list[str] = []
    state_path = tmp_path / sample.dataset_version / sample.start.source_state
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(b"sample state")
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)

    class FakeGame:
        def use_start_state(self, path: Path) -> None:
            assert path == state_path
            events.append("state")

        def release_lease(self) -> None:
            events.append("release")

    class FakeHarness:
        def run(self, run_id: str, tasks: list, *, sample_id: str):
            assert run_id == f"eval-{sample.sample_id}"
            assert sample_id == sample.sample_id
            events.append("run")
            if failure is not None:
                raise failure("run failed")
            return SimpleNamespace(
                model_dump_json=lambda **kwargs: '{"termination":"success"}', branch="main"
            )

    monkeypatch.setattr(
        runner,
        "build_real",
        lambda **kwargs: (FakeHarness(), FakeGame()),
    )

    runner.run_one(sample, tmp_path / "work", run_config_path="config.json")

    assert events == ["state", "run", "release"]
    record = json.loads((tmp_path / "work" / "run.json").read_text("utf-8"))
    assert bool(record["error"]) is (failure is RuntimeError)
    assert not record["invalid"]


def test_consecutive_samples_can_acquire_the_same_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned: list[str] = []
    samples = load_samples()[:2]
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path / "dataset")
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)

    class FakeGame:
        def __init__(self, sample_id: str) -> None:
            self.sample_id = sample_id

        def use_start_state(self, path: Path) -> None:
            assert self.sample_id in str(path)

        def release_lease(self) -> None:
            owned.clear()

    class FakeHarness:
        def run(self, run_id: str, tasks: list, *, sample_id: str):
            return SimpleNamespace(
                model_dump_json=lambda **kwargs: '{"termination":"success"}', branch="main"
            )

    def build(**kwargs: object) -> tuple[FakeHarness, FakeGame]:
        assert not owned, "previous sample still holds the lease"
        overlay = json.loads(Path(kwargs["config"][1]).read_text("utf-8"))
        sample_id = overlay["run"]["run_id"].removeprefix("eval-")
        owned.append(sample_id)
        return FakeHarness(), FakeGame(sample_id)

    monkeypatch.setattr(runner, "build_real", build)

    for index, sample in enumerate(samples):
        state_path = tmp_path / "dataset" / sample.dataset_version / sample.start.source_state
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_bytes(b"sample state")
        runner.run_one(sample, tmp_path / str(index), run_config_path="config.json")
        assert not owned
