"""Unit tests for deterministic frozen short-dataset construction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.agent_short_goal_run.dataset.build.short_frozen import build_dataset
from evals.agent_short_goal_run.dataset.loader import validate_tiers
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.one import loop_overrides, run_arguments
from pokemon_agent.brain import Task


def _sample(sample_id: str, state_name: str) -> dict:
    return {
        "sample_id": sample_id,
        "dataset_version": "v20261021_retest5",
        "granularity": "run",
        "category": "shop",
        "start": {
            "kind": "state",
            "archive": "",
            "source_state": f"states/{state_name}",
            "source_sha256": "a" * 64,
        },
        "goal": "run goal",
        "success_criteria": "run criterion",
        "max_steps": 9,
        "initial_state_hint": "hint",
        "behavior": "behavior",
        "check_id": None,
        "rubric": [],
        "red_lines": [],
        "k_metric": "pass_at_k",
        "split": "test",
    }


def _task_entry(sample_id: str, count: int) -> dict:
    return {
        "sample_id": sample_id,
        "episode": {
            "goal": f"episode {sample_id}",
            "success_criteria": "episode done",
            "max_steps": count,
        },
        "tasks": [
            {"goal": f"task {index}", "success_criteria": f"task {index} done", "max_steps": 4}
            for index in range(count)
        ],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[dict]]:
    dataset_root = tmp_path / "dataset"
    parent = dataset_root / "v20261021_retest5"
    (parent / "states").mkdir(parents=True)
    samples = [_sample("alpha", "alpha.state"), _sample("beta", "beta.state")]
    for sample in samples:
        (parent / sample["start"]["source_state"]).write_bytes(sample["sample_id"].encode())
    (parent / "samples.jsonl").write_text(
        "\n".join(json.dumps(sample, separators=(",", ":")) for sample in samples) + "\n",
        encoding="utf-8",
    )
    (parent / "rubric.json").write_text("{}", encoding="utf-8")
    (parent / "coverage.md").write_text("coverage\n", encoding="utf-8")
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps([_task_entry("alpha", 1), _task_entry("beta", 2)]), encoding="utf-8"
    )
    return dataset_root, tasks_path, dataset_root / "v20261028_short_frozen", samples


def test_builder_changes_only_version_tier_and_goals(tmp_path: Path) -> None:
    dataset_root, tasks_path, target, original_samples = _fixture(tmp_path)

    build_dataset(dataset_root, tasks_path)

    built = [json.loads(line) for line in (target / "samples.jsonl").read_text().splitlines()]
    entries = {entry["sample_id"]: entry for entry in json.loads(tasks_path.read_text())}
    for before, after in zip(original_samples, built, strict=True):
        unchanged_before = {
            key: value
            for key, value in before.items()
            if key not in {"dataset_version", "tier", "goals"}
        }
        assert {
            key: value
            for key, value in after.items()
            if key not in {"dataset_version", "tier", "goals"}
        } == unchanged_before
        assert after["dataset_version"] == "v20261028_short_frozen"
        assert after["tier"] == "short"
        assert after["goals"] == [
            {
                **entries[after["sample_id"]]["episode"],
                "tasks": entries[after["sample_id"]]["tasks"],
            }
        ]
        assert after["goals"][0]["max_steps"] == len(after["goals"][0]["tasks"])
    validate_tiers([EvalSample.model_validate(sample) for sample in built])
    assert (target / "states" / "alpha.state").read_bytes() == b"alpha"


def test_builder_rejects_existing_target(tmp_path: Path) -> None:
    dataset_root, tasks_path, target, _ = _fixture(tmp_path)
    target.mkdir()

    with pytest.raises(FileExistsError):
        build_dataset(dataset_root, tasks_path)


@pytest.mark.parametrize(
    "task_entries",
    [
        [_task_entry("alpha", 1)],
        [_task_entry("alpha", 1), _task_entry("beta", 1), _task_entry("unknown", 1)],
    ],
)
def test_builder_rejects_missing_or_unknown_samples(
    tmp_path: Path, task_entries: list[dict]
) -> None:
    dataset_root, tasks_path, target, _ = _fixture(tmp_path)
    tasks_path.write_text(json.dumps(task_entries), encoding="utf-8")

    with pytest.raises(ValueError, match="sample set mismatch"):
        build_dataset(dataset_root, tasks_path)
    assert not target.exists()


def test_short_sample_arguments_freeze_tasks_and_both_planning_layers() -> None:
    data = _sample("shop", "shop.state")
    data.update(
        dataset_version="v20261028_short_frozen",
        tier="short",
        goals=[
            {
                "goal": "talk to two customers",
                "success_criteria": "both interacted",
                "max_steps": 2,
                "tasks": [
                    {"goal": "customer one", "success_criteria": "one", "max_steps": 4},
                    {"goal": "customer two", "success_criteria": "two", "max_steps": 4},
                ],
            }
        ],
    )
    sample = EvalSample.model_validate(data)

    goals, frozen_tasks = run_arguments(sample)

    assert [(goal.task_id, goal.goal, goal.max_steps) for goal in goals] == [
        ("shop-g1", "talk to two customers", 2)
    ]
    assert frozen_tasks == {
        "shop-g1": [
            Task(task_id="shop-g1-t1", goal="customer one", success_criteria="one", max_steps=4),
            Task(task_id="shop-g1-t2", goal="customer two", success_criteria="two", max_steps=4),
        ]
    }
    assert loop_overrides(sample) == {"freeze_run_plan": True, "freeze_episode_plan": True}


def test_builder_copies_states_and_version_files(tmp_path: Path) -> None:
    dataset_root, tasks_path, target, _ = _fixture(tmp_path)
    parent = dataset_root / "v20261021_retest5"
    build_dataset(dataset_root, tasks_path)

    for filename in ("rubric.json", "coverage.md"):
        assert (target / filename).read_bytes() == (parent / filename).read_bytes()
    assert sorted(path.name for path in (target / "states").iterdir()) == [
        "alpha.state",
        "beta.state",
    ]
