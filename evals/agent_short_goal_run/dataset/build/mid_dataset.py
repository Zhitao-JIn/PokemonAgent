"""构建确定性的 v20261028_mid 数据集版本。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from evals.agent_short_goal_run.dataset.build.mid_starts import (
    m3_hp_consistency_issues,
    regenerate_m3_dataset,
    write_derived_starts,
)
from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.one import run_arguments
from pokemon_agent.world import RamReadout, TaskObservation

PARENT_VERSION = "v20261021_retest5"
NEW_VERSION = "v20261028_mid"
ORACLE_STEPS = {
    "mid_walk_to_pallet": 22,
    "mid_heal_buy_return": 83,
    "mid_catch_then_heal": 61,
    "mid_customers_hint_buy": 108,
    "mid_cure_poison_budget": 76,
}
M1_ORACLE_SUMMARY = {
    "no_encounter": 6,
    "median": 22,
    "max": 98,
    "encounter_rate": 0.6,
}
DATA_ROOT = Path(__file__).resolve().parent.parent


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(
    dataset_root: Path,
    goals_path: Path,
    *,
    target_dir: Path | None = None,
    prepared_states: Path | None = None,
    validate: bool = True,
) -> Path:
    """从父版样本与预备起点构建新版本；默认独立生成派生存档和运行期预检。"""
    parent_dir = dataset_root / PARENT_VERSION
    output_dir = target_dir or dataset_root / NEW_VERSION
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing dataset: {output_dir}")
    specs = json.loads(goals_path.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or len(specs) != 5:
        raise ValueError("mid_goals.json must contain exactly five sample specifications")
    ids = [entry.get("sample_id") for entry in specs]
    if len(ids) != len(set(ids)) or set(ids) != set(ORACLE_STEPS):
        raise ValueError(f"unexpected mid sample ids: {ids}")
    parent_samples = [
        json.loads(line)
        for line in (parent_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_id = {item["sample_id"]: item for item in parent_samples}
    selected = []
    for entry in specs:
        source_id = entry["source_sample_id"]
        if source_id not in by_id:
            raise ValueError(f"unknown parent sample: {source_id}")
        selected.append((entry, by_id[source_id]))
    if prepared_states is None:
        with tempfile.TemporaryDirectory(prefix="mid-starts-") as temporary:
            temp_states = Path(temporary) / "states"
            state_records = write_derived_starts(Path("assets/rom"), parent_dir, temp_states)
            return _write_dataset(
                parent_dir, output_dir, goals_path, selected, temp_states, state_records, validate
            )
    records = _state_records(parent_dir, prepared_states, specs)
    return _write_dataset(
        parent_dir, output_dir, goals_path, selected, prepared_states, records, validate
    )


def _write_dataset(
    parent_dir: Path,
    output_dir: Path,
    goals_path: Path,
    selected: list[tuple[dict[str, Any], dict[str, Any]]],
    prepared_states: Path,
    state_records: dict[str, dict[str, Any]],
    validate: bool,
) -> Path:
    output_dir.mkdir(parents=True)
    states_dir = output_dir / "states"
    states_dir.mkdir()
    updated: list[str] = []
    sample_records: dict[str, dict[str, Any]] = {}
    for entry, original in selected:
        output_state = entry["output_state"].removeprefix("states/")
        source_state = prepared_states / output_state
        if not source_state.is_file():
            raise FileNotFoundError(source_state)
        copied_state = states_dir / output_state
        shutil.copyfile(source_state, copied_state)
        digest = sha256_of(copied_state)
        start = dict(original["start"])
        start.update(
            kind="state", archive="", source_state=f"states/{output_state}", source_sha256=digest
        )
        goals = [
            {
                "goal": goal["goal"],
                "success_criteria": goal["success_criteria"],
                "max_steps": goal["max_steps"],
            }
            for goal in entry["goals"]
        ]
        sample = dict(original)
        sample.update(
            sample_id=entry["sample_id"],
            dataset_version=NEW_VERSION,
            tier="mid",
            start=start,
            goal=entry["goal"],
            success_criteria=entry["success_criteria"],
            max_steps=entry["max_steps"],
            goals=goals,
            initial_state_hint=entry["initial_state_hint"],
            behavior=entry["behavior"],
            check_id=entry["check_id"],
        )
        model = EvalSample.model_validate(sample)
        if validate:
            ram, observation, event_flags, m3_hud = _perceive_state(copied_state)
            validate_start(model, ram, observation)
            if entry["check_id"] == "customer_hint_purchase" and event_flags & 0x02 == 0:
                raise ValueError("customer_hint_purchase requires D74E bit1=1 at build time")
            if model.check_id == "catch_then_heal":
                if observation.takeover is None:
                    raise ValueError("M3 battle scene has no decoded battle view")
                if (observation.takeover.mine.hp, observation.takeover.mine.max_hp) != (12, 25):
                    raise ValueError(
                        "M3 decoded battle HP must be 12/25, got "
                        f"{observation.takeover.mine.hp}/{observation.takeover.mine.max_hp}"
                    )
                issues = m3_hp_consistency_issues(
                    ram.party[0].hp,
                    observation.takeover.mine.hp,
                    observation.facts.screen,
                    m3_hud,
                )
                if issues:
                    raise ValueError(f"M3 HP/HUD inconsistency: {', '.join(issues)}")
        goals_for_runner, frozen_tasks = run_arguments(model)
        if not goals_for_runner or frozen_tasks is not None:
            raise ValueError(f"mid plan assembly invalid for {model.sample_id}")
        updated.append(json.dumps(sample, ensure_ascii=False, separators=(",", ":")))
        source_name = original["start"]["source_state"]
        sample_record = {
            "oracle_steps": entry["oracle_steps"],
            "source_state": source_name,
            "source_sha256": state_records[output_state]["source_sha256"],
            "output_state": f"states/{output_state}",
            "state_sha256": digest,
            "ram_edits": [
                {
                    "address": f"0x{edit['address']:04X}",
                    "before": f"0x{edit['before']:02X}",
                    "after": f"0x{edit['after']:02X}",
                }
                for edit in state_records[output_state]["edits"]
            ],
            "max_steps": model.max_steps,
        }
        if model.sample_id == "mid_walk_to_pallet":
            sample_record["oracle_summary"] = M1_ORACLE_SUMMARY
        sample_records[model.sample_id] = sample_record

    (output_dir / "samples.jsonl").write_text("\n".join(updated) + "\n", encoding="utf-8")
    shutil.copyfile(parent_dir / "rubric.json", output_dir / "rubric.json")
    coverage = [
        "# v20261028_mid coverage",
        "",
        "| sample_id | tier | episodes | check_id | start | oracle_steps | max_steps |",
        "|---|---|---:|---|---|---:|---:|",
    ]
    for entry, _original in selected:
        coverage.append(
            "| "
            f"{entry['sample_id']} | mid | {len(entry['goals'])} | {entry['check_id']} | "
            f"{entry['output_state']} | {entry['oracle_steps']} | {entry['max_steps']} |"
        )
    (output_dir / "coverage.md").write_text("\n".join(coverage) + "\n", encoding="utf-8")
    revision = {
        "parent_version": PARENT_VERSION,
        "change": "新增五条冻结 episode 目标的中期评测样本；M2、M3、M5 使用确定性 RAM 派生起点",
        "samples": sample_records,
        "source_files": {
            "mid_goals.json": sha256_of(goals_path),
            "parent_samples.jsonl": sha256_of(parent_dir / "samples.jsonl"),
            "parent_rubric.json": sha256_of(parent_dir / "rubric.json"),
            **{
                record["output_state"]: record["state_sha256"] for record in sample_records.values()
            },
        },
    }
    (output_dir / "revision.json").write_text(
        json.dumps(revision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_dir


def _state_records(
    parent_dir: Path, states_dir: Path, specs: list[dict]
) -> dict[str, dict[str, Any]]:
    parent_samples = {
        row["sample_id"]: row
        for row in (
            json.loads(line)
            for line in (parent_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    records: dict[str, dict[str, Any]] = {}
    for entry in specs:
        filename = entry["output_state"].removeprefix("states/")
        source_state = entry.get("source_state")
        if source_state is None:
            source_state = parent_samples[entry["source_sample_id"]]["start"]["source_state"]
        source = parent_dir / "states" / source_state.removeprefix("states/")
        records[filename] = {
            "source_sha256": sha256_of(source),
            "edits": [],
        }
    if not states_dir.is_dir():
        raise FileNotFoundError(states_dir)
    return records


def _perceive_state(state_path: Path) -> tuple[RamReadout, TaskObservation, int, list[int]]:
    """加载真实起点并复用世界的 RAM/屏幕解码实现，不推进按键。"""
    from pyboy import PyBoy

    from pokemon_agent.world.ram import map_settled, read_terrain
    from pokemon_agent.world.screen_text import read_screen_text, read_tiles
    from pokemon_agent.world.task_perception import observe_task

    emulator = PyBoy("assets/rom", window="null", sound_emulated=False)
    try:
        with state_path.open("rb") as stream:
            emulator.load_state(stream)
        emulator.tick(1)
        memory = emulator.memory
        text = read_screen_text(memory)
        terrain = read_terrain(memory) if map_settled(memory) else None
        image_buffer = __import__("io").BytesIO()
        emulator.screen.image.save(image_buffer, format="PNG")
        perceived = observe_task(
            terrain,
            text,
            image_buffer.getvalue(),
            memory=memory,
            rom=Path("assets/rom").read_bytes(),
            closed=False,
        )
        tiles = read_tiles(memory)
        return (
            perceived.ram,
            perceived.observation,
            memory[0xD74E],
            tiles[9][12:18],
        )
    finally:
        emulator.stop(save=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regenerate-m3", action="store_true")
    args = parser.parse_args()
    goals_path = Path(__file__).with_name("mid_goals.json")
    if args.regenerate_m3:
        print(
            regenerate_m3_dataset(
                DATA_ROOT / PARENT_VERSION,
                DATA_ROOT / NEW_VERSION,
                rom=Path("assets/rom"),
                perceive_state=_perceive_state,
            )
        )
    else:
        print(build_dataset(DATA_ROOT, goals_path))


if __name__ == "__main__":
    main()
