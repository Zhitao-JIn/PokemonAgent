"""治疗样本在加载原始状态后先核起点，不合格时不进入 run 图。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _doubles.script_frames import frame

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.runner import one as runner
from pokemon_agent.schemas.harness import FromHarnessToGameToolResetReq
from pokemon_agent.world.interface import PartyMon


@pytest.mark.parametrize("hp", [0, 20])
def test_invalid_healing_start_is_recorded_without_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hp: int
) -> None:
    sample = next(item for item in load_samples() if item.check_id == "party_healed")
    observation, ram = frame()
    ram = ram.model_copy(
        update={"party": [PartyMon(species=1, level=5, hp=hp, max_hp=20, status="ok")]}
    )
    run_calls: list[object] = []
    state_path = tmp_path / sample.dataset_version / sample.start.source_state
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(b"sample state")
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)

    class FakeGame:
        def use_start_state(self, path: Path) -> None:
            assert path == state_path

        def reset(self, req: FromHarnessToGameToolResetReq) -> None:
            assert req.task.task_id == sample.sample_id
            self.ready = True

        def perceive_task(self):
            assert getattr(self, "ready", False), "perceive_task() before reset()"
            return SimpleNamespace(ram=ram, observation=observation)

        def release_lease(self) -> None:
            pass

    class FakeHarness:
        def run(self, *args, **kwargs):
            run_calls.append(args)

    monkeypatch.setattr(runner, "build_real", lambda **kwargs: (FakeHarness(), FakeGame()))

    runner.run_one(sample, tmp_path / "work", run_config_path="config.json")

    record = json.loads((tmp_path / "work" / "run.json").read_text("utf-8"))
    assert sample.sample_id in record["invalid"]
    assert sample.check_id in record["invalid"]
    assert not run_calls


def test_valid_healing_start_reaches_run_after_perception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = next(item for item in load_samples() if item.check_id == "party_healed")
    observation, ram = frame()
    ram = ram.model_copy(
        update={"party": [PartyMon(species=1, level=5, hp=10, max_hp=20, status="ok")]}
    )
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

        def reset(self, req: FromHarnessToGameToolResetReq) -> None:
            assert req.task.task_id == sample.sample_id
            self.ready = True
            events.append("reset")

        def perceive_task(self):
            assert getattr(self, "ready", False), "perceive_task() before reset()"
            events.append("perceive")
            return SimpleNamespace(ram=ram, observation=observation)

        def release_lease(self) -> None:
            events.append("release")

    class FakeHarness:
        def run(self, run_id: str, goals: list, run_goal=None, *, start_task=None, sample_id=""):
            events.append("run")
            return SimpleNamespace(
                model_dump_json=lambda **kwargs: '{"termination":"success"}', branch="main"
            )

    monkeypatch.setattr(runner, "build_real", lambda **kwargs: (FakeHarness(), FakeGame()))

    runner.run_one(sample, tmp_path / "work", run_config_path="config.json")

    assert events == ["state", "reset", "perceive", "run", "release"]
    record = json.loads((tmp_path / "work" / "run.json").read_text("utf-8"))
    assert not record["invalid"]
