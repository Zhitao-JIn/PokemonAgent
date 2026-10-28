"""Synthetic regression tests for the mid dataset builder and start transforms."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.build import mid_starts, preconditions
from evals.agent_short_goal_run.dataset.build.mid_dataset import build_dataset
from evals.agent_short_goal_run.dataset.build.mid_starts import (
    derive_m2,
    derive_m3,
    derive_m5,
    m3_hp_consistency_issues,
    m3_hud_bar_tiles,
)
from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.agent_short_goal_run.dataset.loader import validate_tiers
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.one import loop_overrides, run_arguments
from evals.dataset.errors import DatasetError
from pokemon_agent.world import TaskScene
from pokemon_agent.world.interface.domain.takeover_view import BattleMenuView


def _sample(sample_id: str, source_state: str) -> dict:
    return {
        "sample_id": sample_id,
        "dataset_version": "v20261021_retest5",
        "granularity": "run",
        "category": "test",
        "start": {
            "kind": "archive",
            "archive": source_state.removesuffix(".state"),
            "source_state": f"states/{source_state}",
            "source_sha256": "a" * 64,
        },
        "goal": "old goal",
        "success_criteria": "old criteria",
        "max_steps": 9,
        "initial_state_hint": "old hint",
        "behavior": "old behavior",
        "check_id": "old_check",
        "rubric": [],
        "red_lines": [],
        "k_metric": "pass_at_k",
        "split": "test",
    }


def _spec(sample_id: str, source_id: str, source_file: str, output_file: str) -> dict:
    return {
        "sample_id": sample_id,
        "source_sample_id": source_id,
        "source_state": f"states/{source_file}",
        "output_state": f"states/{output_file}",
        "goal": f"run {sample_id}",
        "success_criteria": "done",
        "behavior": "do the steps",
        "initial_state_hint": "hint",
        "check_id": "walk_to_pallet",
        "max_steps": 90,
        "oracle_steps": 22,
        "goals": [{"goal": "episode", "success_criteria": "episode done", "max_steps": 4}],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[dict]]:
    dataset_root = tmp_path / "dataset"
    parent = dataset_root / "v20261021_retest5"
    (parent / "states").mkdir(parents=True)
    sources = ["alpha", "beta", "gamma", "delta", "epsilon"]
    samples = [_sample(name, f"{name}.state") for name in sources]
    for sample in samples:
        source = parent / sample["start"]["source_state"]
        source.write_bytes(sample["sample_id"].encode())
    (parent / "samples.jsonl").write_text(
        "\n".join(json.dumps(item) for item in samples) + "\n", encoding="utf-8"
    )
    (parent / "rubric.json").write_text(
        '{"version":"test","items":[],"red_lines":[]}', encoding="utf-8"
    )
    sample_ids = [
        "mid_walk_to_pallet",
        "mid_heal_buy_return",
        "mid_catch_then_heal",
        "mid_customers_hint_buy",
        "mid_cure_poison_budget",
    ]
    specs = [
        _spec(sample_ids[index], source, f"{source}.state", f"out_{index}.state")
        for index, source in enumerate(sources)
    ]
    goals = tmp_path / "goals.json"
    goals.write_text(json.dumps(specs), encoding="utf-8")
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    for entry in specs:
        (prepared / Path(entry["output_state"]).name).write_bytes(entry["sample_id"].encode())
    return dataset_root, goals, prepared, specs


def test_mid_builder_keeps_only_episode_goals_and_copies_starts(tmp_path: Path) -> None:
    dataset_root, goals_path, prepared, specs = _fixture(tmp_path)
    output = build_dataset(dataset_root, goals_path, prepared_states=prepared, validate=False)

    rows = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
    samples = [EvalSample.model_validate(row) for row in rows]
    validate_tiers(samples)
    for row, spec in zip(rows, specs, strict=True):
        assert row["tier"] == "mid"
        assert row["check_id"] == spec["check_id"]
        assert row["max_steps"] == spec["max_steps"]
        assert row["goals"] == spec["goals"]
        assert "tasks" not in row["goals"][0]
        assert (output / spec["output_state"]).read_bytes() == (
            prepared / Path(spec["output_state"]).name
        ).read_bytes()
        goals, frozen = run_arguments(EvalSample.model_validate(row))
        assert [(goal.goal, goal.max_steps) for goal in goals] == [("episode", 4)]
        assert frozen is None
        assert loop_overrides(EvalSample.model_validate(row)) == {"freeze_run_plan": True}
    assert (output / "rubric.json").read_bytes() == (
        dataset_root / "v20261021_retest5" / "rubric.json"
    ).read_bytes()


def test_mid_builder_refuses_existing_output(tmp_path: Path) -> None:
    dataset_root, goals_path, prepared, _ = _fixture(tmp_path)
    target = dataset_root / "v20261028_mid"
    target.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        build_dataset(dataset_root, goals_path, prepared_states=prepared)


@pytest.mark.parametrize("drop_last", [True, False])
def test_mid_builder_rejects_wrong_sample_count(tmp_path: Path, drop_last: bool) -> None:
    dataset_root, goals_path, prepared, specs = _fixture(tmp_path)
    entries = specs[:-1] if drop_last else [*specs, specs[0]]
    goals_path.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly five"):
        build_dataset(dataset_root, goals_path, prepared_states=prepared)


class FakeMemory:
    def __init__(self, initial: dict[int, int]) -> None:
        self.values = initial

    def __getitem__(self, address: int) -> int:
        return self.values[address]

    def __setitem__(self, address: int, value: int) -> None:
        self.values[address] = value


def test_mid_ram_transforms_set_expected_bytes_and_refuse_wrong_source_values() -> None:
    m2 = FakeMemory({0xD16D: 0x19})
    assert derive_m2(m2) == [{"address": 0xD16D, "before": 0x19, "after": 0x0C}]
    m3 = FakeMemory(
        {
            0xD16D: 0x19,
            0xD015: 0,
            0xD016: 0x19,
            0xC3A0 + 9 * 20 + 14: 0x6B,
            0xC3A0 + 9 * 20 + 15: 0x6B,
            0xC3A0 + 9 * 20 + 16: 0x6B,
            0xC3A0 + 9 * 20 + 17: 0x6B,
            0xC3A0 + 10 * 20 + 12: 0xF8,
            0xC3A0 + 10 * 20 + 13: 0xFB,
        }
    )
    assert [(edit["address"], edit["after"]) for edit in derive_m3(m3)] == [
        (0xD16D, 0x0C),
        (0xD015, 0),
        (0xD016, 0x0C),
        (0xC3A0 + 9 * 20 + 14, 0x6A),
        (0xC3A0 + 9 * 20 + 15, 0x63),
        (0xC3A0 + 9 * 20 + 16, 0x63),
        (0xC3A0 + 9 * 20 + 17, 0x63),
        (0xC3A0 + 10 * 20 + 12, 0xF7),
        (0xC3A0 + 10 * 20 + 13, 0xF8),
    ]
    m5 = FakeMemory({0xD19B: 0})
    assert derive_m5(m5) == [{"address": 0xD19B, "before": 0, "after": 8}]
    with pytest.raises(ValueError, match="expected RAM"):
        derive_m2(FakeMemory({0xD16D: 0x0C}))


def test_m3_hp_consistency_accepts_matching_decoded_hud_and_bar() -> None:
    screen = " PIDGEY\n HP:[██████]\n BULBASAUR\n HP:[██▉   ]\n 12/ 25"
    assert m3_hud_bar_tiles(12, 25) == [0x6B, 0x6B, 0x6A, 0x63, 0x63, 0x63]
    assert m3_hp_consistency_issues(12, 12, screen, [0x6B, 0x6B, 0x6A, 0x63, 0x63, 0x63]) == []


@pytest.mark.parametrize(
    ("party_hp", "battle_hp", "screen", "tiles", "expected"),
    [
        (12, 17, "12/ 25", [0x6B, 0x6B, 0x6A, 0x63, 0x63, 0x63], "battle cache"),
        (12, 12, "25/ 25", [0x6B, 0x6B, 0x6A, 0x63, 0x63, 0x63], "decoded HUD"),
        (12, 12, "12/ 25", [0x6B] * 6, "bar tiles"),
    ],
)
def test_m3_hp_consistency_reports_each_mismatch(
    party_hp: int, battle_hp: int, screen: str, tiles: list[int], expected: str
) -> None:
    assert expected in "; ".join(m3_hp_consistency_issues(party_hp, battle_hp, screen, tiles))


def test_m3_regeneration_updates_only_its_state_and_hash_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_root = tmp_path / "dataset"
    output = dataset_root / "v20261028_mid"
    states = output / "states"
    states.mkdir(parents=True)
    parent = dataset_root / "v20261021_retest5"
    parent.mkdir(parents=True)
    (states / "m3_bulbasaur_half_hp_battle.state").write_bytes(b"old m3")
    untouched = {
        "knowledge_pokemon_center_enter.state": b"m1",
        "m2_bulbasaur_half_hp.state": b"m2",
        "knowledge_shop_interaction.state": b"m4",
        "m5_pidgey_poisoned.state": b"m5",
    }
    for name, content in untouched.items():
        (states / name).write_bytes(content)
    m3_row = _sample("mid_catch_then_heal", "m3_bulbasaur_half_hp_battle.state")
    m3_row["start"]["kind"] = "state"
    m3_row["start"]["source_sha256"] = "a" * 64
    m3_row["check_id"] = "catch_then_heal"
    other_row = _sample("other", "other.state")
    (output / "samples.jsonl").write_text(
        json.dumps(m3_row, separators=(",", ":"))
        + "\n"
        + json.dumps(other_row, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    revision = {
        "samples": {
            "mid_catch_then_heal": {
                "state_sha256": "a" * 64,
                "ram_edits": [],
                "max_steps": 190,
            }
        },
        "source_files": {"states/m3_bulbasaur_half_hp_battle.state": "a" * 64},
    }
    (output / "revision.json").write_text(json.dumps(revision), encoding="utf-8")

    def regenerate(_rom: Path, _parent: Path, target_dir: Path) -> dict[str, object]:
        (target_dir / "m3_bulbasaur_half_hp_battle.state").write_bytes(b"new m3")
        return {
            "source_sha256": "b" * 64,
            "sha256": "c" * 64,
            "edits": [
                {"address": 0xD16D, "before": 25, "after": 12},
                {"address": 0xC3A0 + 9 * 20 + 14, "before": 0x6B, "after": 0x6A},
            ],
        }

    monkeypatch.setattr(mid_starts, "write_derived_m3_state", regenerate)
    monkeypatch.setattr(preconditions, "validate_start", lambda *_args: None)
    perceived = (
        SimpleNamespace(party=[SimpleNamespace(hp=12)]),
        SimpleNamespace(
            takeover=SimpleNamespace(mine=SimpleNamespace(hp=12)),
            facts=SimpleNamespace(screen="12/25"),
        ),
        0,
        [0x6B, 0x6B, 0x6A, 0x63, 0x63, 0x63],
    )
    mid_starts.regenerate_m3_dataset(
        parent,
        output,
        rom=tmp_path / "rom",
        perceive_state=lambda _path: perceived,
    )

    assert (states / "m3_bulbasaur_half_hp_battle.state").read_bytes() == b"new m3"
    assert {name: (states / name).read_bytes() for name in untouched} == untouched
    lines = (output / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["start"]["source_sha256"] == "c" * 64
    assert lines[1] == json.dumps(other_row, separators=(",", ":"))
    updated_revision = json.loads((output / "revision.json").read_text(encoding="utf-8"))
    assert updated_revision["samples"]["mid_catch_then_heal"]["state_sha256"] == "c" * 64
    assert updated_revision["samples"]["mid_catch_then_heal"]["screen_edits"][0]["row"] == 9


def _runtime(
    check_id: str, *, valid: bool = True
) -> tuple[EvalSample, SimpleNamespace, SimpleNamespace]:
    sample_data = _sample("synthetic", "x.state")
    sample_data.update(
        check_id=check_id, goals=[{"goal": "g", "success_criteria": "c", "max_steps": 1}]
    )
    sample = EvalSample.model_validate(sample_data)
    party = [
        SimpleNamespace(
            species=1,
            level=5,
            hp=12 if check_id in {"heal_buy_return", "catch_then_heal"} else 25,
            max_hp=25,
            status="ok",
        ),
        SimpleNamespace(
            species=16,
            level=3,
            hp=12,
            max_hp=12,
            status="PSN" if check_id == "cure_poison_budget" else "ok",
        ),
    ]
    bag = [SimpleNamespace(item_id=4, quantity=4), SimpleNamespace(item_id=20, quantity=1)]
    money = 3000 if check_id == "customer_hint_purchase" else 2000
    ram = SimpleNamespace(
        in_battle=check_id == "catch_then_heal", party=party, bag=bag, money=money
    )
    map_id = {
        "walk_to_pallet": 1,
        "heal_buy_return": 1,
        "catch_then_heal": 12,
        "customer_hint_purchase": 42,
        "cure_poison_budget": 1,
    }[check_id]
    scene = (
        TaskScene.WALK
        if check_id in {"walk_to_pallet", "heal_buy_return"}
        else TaskScene.BATTLE_MENU
    )
    if check_id == "catch_then_heal":
        battle = BattleMenuView.model_construct(
            trainer=False,
            mine=SimpleNamespace(hp=12, max_hp=25),
            foe=SimpleNamespace(),
            party=[],
            bag=[],
        )
    else:
        battle = None
    observation = SimpleNamespace(
        place=SimpleNamespace(map_id=map_id),
        scene=scene,
        takeover=battle,
        facts=SimpleNamespace(screen="12/ 25" if check_id == "catch_then_heal" else ""),
    )
    if not valid:
        if check_id == "walk_to_pallet":
            ram.party[0].hp = 0
        elif check_id == "catch_then_heal":
            ram.in_battle = False
        else:
            ram.money = 3
    return sample, ram, observation


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
def test_mid_preconditions_accept_valid_synthetic_starts(check_id: str) -> None:
    sample, ram, observation = _runtime(check_id)
    validate_start(sample, ram, observation)


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
def test_mid_preconditions_reject_invalid_synthetic_starts(check_id: str) -> None:
    sample, ram, observation = _runtime(check_id, valid=False)
    with pytest.raises(DatasetError):
        validate_start(sample, ram, observation)
