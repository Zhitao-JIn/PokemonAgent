"""取消购买起点从原始状态感知确认框后才允许进入 run 图。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _doubles.script_frames import frame

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.runner import one as runner
from pokemon_agent.schemas.harness import FromHarnessToGameToolResetReq
from pokemon_agent.world import TaskScene
from pokemon_agent.world.interface import DecodedText


@pytest.mark.parametrize(
    "options,valid", [(["YES", "NO"], True), (["BUY", "SELL", "QUIT"], False), ([], False)]
)
def test_cancel_start_validation_controls_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: list[str],
    valid: bool,
) -> None:
    sample = next(item for item in load_samples() if item.check_id == "shop_cancelled")
    observation, ram = frame()
    observation = observation.model_copy(update={"scene": TaskScene.SHOP_ITEMS})
    ram = ram.model_copy(
        update={"decoded": DecodedText(options=options, cursor="", dialog_text="")}
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
        def run(self, run_id: str, tasks: list, *, sample_id: str):
            run_calls.append((run_id, sample_id))
            return SimpleNamespace(
                model_dump_json=lambda **kwargs: '{"termination":"success"}', branch="main"
            )

    monkeypatch.setattr(runner, "build_real", lambda **kwargs: (FakeHarness(), FakeGame()))

    runner.run_one(sample, tmp_path / "work", run_config_path="config.json")

    record = json.loads((tmp_path / "work" / "run.json").read_text("utf-8"))
    if valid:
        assert run_calls == [(f"eval-{sample.sample_id}", sample.sample_id)]
        assert not record["invalid"]
    else:
        assert not run_calls
        assert sample.sample_id in record["invalid"]
        assert sample.check_id in record["invalid"]
