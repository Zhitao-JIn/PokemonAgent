"""起点预检顺序和 worker 失败记录的离线回归。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.build.preconditions import PREFLIGHT_CHECK_IDS
from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.record import RunOneRecord
from evals.agent_short_goal_run.solver.runner import one as runner
from evals.agent_short_goal_run.solver.runner.failure import exception_leaves
from pokemon_agent.schemas.harness import FromHarnessToGameToolResetReq


def nested_failure() -> ExceptionGroup:
    """两个层级、三个有序叶子，包含与原故障同形的消息。"""
    return ExceptionGroup(
        "outer",
        [
            ValueError("first"),
            ExceptionGroup("inner", [RuntimeError("perceive_task() before reset()")]),
            OSError("last"),
        ],
    )


def test_nested_exception_group_keeps_leaf_types_messages_and_order() -> None:
    result = exception_leaves(nested_failure())

    assert [leaf.model_dump() for leaf in result] == [
        {"type": "ValueError", "message": "first"},
        {"type": "RuntimeError", "message": "perceive_task() before reset()"},
        {"type": "OSError", "message": "last"},
    ]


class StartGame:
    """绑定存档直到 reset 才载入；模拟真实 MCP 门面的时序。"""

    def __init__(self, sample: EvalSample, fails: bool) -> None:
        self.sample = sample
        self.fails = fails
        self.events: list[str] = []
        self.initial_ram = object()
        self.state: list[object] = []

    def use_start_state(self, path: Path) -> None:
        sample = self.sample
        assert path == runner.DATASET_DIR / sample.dataset_version / sample.start.source_state
        self.events.append("bind")

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        assert req.task.task_id == self.sample.sample_id
        self.state[:] = [self.initial_ram]
        self.events.append("reset")

    def perceive_task(self) -> SimpleNamespace:
        assert self.state, "perceive_task() before reset()"
        self.events.append("perceive")
        if self.fails:
            raise nested_failure()
        return SimpleNamespace(ram=self.state[0], observation=None)

    def release_lease(self) -> None:
        self.events.append("release")


class ResettingHarness:
    """正式 run 仍调用自己的 reset。"""

    def __init__(self, game: StartGame) -> None:
        self.game = game

    def run(
        self,
        run_id: str,
        goals: list,
        run_goal=None,
        *,
        start_task=None,
        sample_id="",
        frozen_tasks=None,
    ):
        self.game.events.append("run")
        self.game.reset(FromHarnessToGameToolResetReq(task=start_task))
        assert self.game.state == [self.game.initial_ram]
        return SimpleNamespace(model_dump_json=lambda **kwargs: "{}", branch="main")


@pytest.mark.parametrize("check_id", ["shop_cancelled", "party_healed"])
@pytest.mark.parametrize("fails", [False, True])
def test_preflight_loads_bound_state_and_preserves_harness_reset_and_failure_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    check_id: str,
    fails: bool,
) -> None:
    sample = next(item for item in load_samples() if item.check_id == check_id)
    game = StartGame(sample, fails)
    events = game.events
    work = tmp_path / "work"
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)

    def validate(sample: object, ram: object, observation: object) -> None:
        assert ram is game.initial_ram
        events.append("validate")
        game.state.clear()

    monkeypatch.setattr(runner, "build_real", lambda **kwargs: (ResettingHarness(game), game))
    monkeypatch.setattr(runner, "validate_start", validate)

    runner.run_one(sample, work, run_config_path="unused.json")

    payload = json.loads((work / "run.json").read_text("utf-8"))
    record = RunOneRecord.model_validate(payload)
    assert not record.invalid
    if fails:
        assert events == ["bind", "reset", "perceive", "release"]
        assert "stage=preflight_perceive" in record.error
        leaves = json.loads(record.error.split("; leaves=", 1)[1])
        assert leaves == [leaf.model_dump() for leaf in exception_leaves(nested_failure())]
        assert record.error in capsys.readouterr().err
        assert not (work / "run_result.json").exists()
        assert not (work / "trace").exists()
    else:
        assert events == ["bind", "reset", "perceive", "validate", "run", "reset", "release"]
        assert not record.error
        assert (work / "run_result.json").is_file()


@pytest.mark.parametrize(
    "check_id",
    [
        "walk_to_pallet",
        "heal_buy_return",
        "catch_then_heal",
        "customer_hint_purchase",
        "cure_poison_budget",
    ],
)
def test_mid_check_ids_use_preflight_reset_and_perceive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check_id: str,
) -> None:
    assert check_id in PREFLIGHT_CHECK_IDS
    base = next(item for item in load_samples() if item.check_id == "party_healed")
    sample = base.model_copy(
        update={
            "sample_id": f"synthetic_{check_id}",
            "dataset_version": "v20261028_mid",
            "check_id": check_id,
        }
    )
    game = StartGame(sample, fails=False)
    work = tmp_path / "work"
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)

    def validate(sample_arg: object, ram: object, observation: object) -> None:
        assert ram is game.initial_ram
        game.events.append("validate")

    monkeypatch.setattr(runner, "build_real", lambda **kwargs: (ResettingHarness(game), game))
    monkeypatch.setattr(runner, "validate_start", validate)

    runner.run_one(sample, work, run_config_path="unused.json")

    record = RunOneRecord.model_validate(json.loads((work / "run.json").read_text("utf-8")))
    assert not record.invalid and not record.error
    assert game.events == ["bind", "reset", "perceive", "validate", "run", "reset", "release"]
