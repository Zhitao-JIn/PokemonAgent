"""长期数据集构建与卧室起点契约的合成测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.build import long_dataset, preconditions
from evals.agent_short_goal_run.dataset.build.long_dataset import build_dataset
from evals.agent_short_goal_run.dataset.build.preconditions import (
    PREFLIGHT_CHECK_IDS,
    validate_start,
)
from evals.agent_short_goal_run.dataset.loader import validate_tiers
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.dataset.errors import DatasetError
from pokemon_agent.world import TaskScene


def _sample() -> EvalSample:
    return EvalSample.model_validate(
        {
            "sample_id": "long_leave_pallet_town",
            "dataset_version": "v20261028_long",
            "tier": "long",
            "granularity": "run",
            "category": "exploration",
            "start": {
                "kind": "state",
                "archive": "",
                "source_state": "states/start.state",
                "source_sha256": "a" * 64,
            },
            "goal": "离开真新镇，一路向北走到镇外。",
            "success_criteria": "criteria",
            "max_steps": 720,
            "goals": [],
            "behavior": "behavior",
            "check_id": "leave_pallet_town",
            "rubric": ["decompose_quality", "strategy_switch", "redundant_path"],
            "red_lines": ["R1", "R2", "R3"],
            "k_metric": "pass_at_k",
            "split": "val",
            "knowledge_exclude_topics": ["map_connections"],
        }
    )


def _ram(
    *, battle: bool = False, party: list | None = None, bag: list | None = None, money: int = 3000
):
    return SimpleNamespace(in_battle=battle, party=party or [], bag=bag or [], money=money)


def _observation(*, map_id: int = 38, scene: TaskScene = TaskScene.WALK):
    return SimpleNamespace(place=SimpleNamespace(map_id=map_id), scene=scene)


def test_long_start_precondition_accepts_and_rejects_synthetic_bedroom() -> None:
    sample = _sample()
    validate_start(sample, _ram(), _observation())

    invalid_starts = [
        (_ram(), _observation(map_id=37)),
        (_ram(), _observation(scene=TaskScene.DIALOG)),
        (_ram(battle=True), _observation()),
        (_ram(party=[object()]), _observation()),
        (_ram(bag=[object()]), _observation()),
        (_ram(money=2999), _observation()),
    ]
    for ram, observation in invalid_starts:
        with pytest.raises(DatasetError):
            validate_start(sample, ram, observation)
    assert "leave_pallet_town" in PREFLIGHT_CHECK_IDS


def test_long_builder_writes_only_contract_fields_and_refuses_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    midpoint = dataset_root / "v20261028_mid"
    midpoint.mkdir()
    rubric = {"version": "old", "items": [], "red_lines": []}
    (midpoint / "rubric.json").write_text(json.dumps(rubric), encoding="utf-8")
    keys = tmp_path / "keys.json"
    keys.write_text("{}", encoding="utf-8")
    route = tmp_path / "route.json"
    route.write_text(
        json.dumps(
            {
                "milestones": [
                    {"name": name, "oracle_steps": long_dataset.MILESTONES[label]}
                    for label, name in long_dataset.ROUTE_NAMES.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    state = b"synthetic bedroom state"
    monkeypatch.setattr(long_dataset, "EXPECTED_SHA256", hashlib.sha256(state).hexdigest())
    monkeypatch.setattr(long_dataset, "generate_pair", lambda *_args: (state, state, []))
    monkeypatch.setattr(long_dataset, "_readout", lambda _state: (object(), object()))
    monkeypatch.setattr(preconditions, "validate_start", lambda *_args: None)

    output = build_dataset(
        dataset_root=dataset_root, keys_path=keys, route_path=route, validate=False
    )
    row = json.loads((output / "samples.jsonl").read_text(encoding="utf-8"))

    assert row["tier"] == "long" and row["goals"] == []
    assert "initial_memory" not in row
    assert row["knowledge_exclude_topics"] == ["map_connections"]
    assert set(row) <= set(EvalSample.model_fields)
    validate_tiers([EvalSample.model_validate(row)])
    with pytest.raises(FileExistsError):
        build_dataset(dataset_root=dataset_root, keys_path=keys, route_path=route)


def test_long_start_keys_file_has_only_valid_fixed_key_sequence() -> None:
    data = json.loads(long_dataset.KEYS_PATH.read_text(encoding="utf-8"))
    keys = data["keys"]
    canonical = json.dumps(keys, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )

    # 此哈希来自实验记录 long_preflight.json 的 33 项按键序列，防止再次错移 down。
    assert hashlib.sha256(canonical).hexdigest() == (
        "4207f551642d32ed5417307146625873ecc82c1759493e0b45bc9eb5a9a32fdd"
    )
    assert data["startup_wait_frames"] == 3000
    assert len(keys) == 33
    assert keys[0] == {"key": "start", "held_frames": 60}
    assert [index for index, item in enumerate(keys) if item["key"] == "down"] == [15, 23]
    assert all(
        item == {"key": "down", "held_frames": 10}
        if index in {15, 23}
        else item == {"key": "start", "held_frames": 60}
        if index == 0
        else item == {"key": "a", "held_frames": 10}
        for index, item in enumerate(keys)
    )
