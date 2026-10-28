"""构建确定性的长期数据集 v20261028_long。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from evals.agent_short_goal_run.dataset.build.long_start import (
    EXPECTED_SHA256,
    generate_pair,
)
from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.agent_short_goal_run.dataset.loader import check, validate_tiers
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from pokemon_agent.world import RamReadout, TaskObservation

NEW_VERSION = "v20261028_long"
DATA_ROOT = Path(__file__).resolve().parent.parent
KEYS_PATH = Path(__file__).with_name("long_start_keys.json")
ROUTE_PATH = Path(__file__).resolve().parents[6] / "experiment" / "long_verify" / "route.json"

MILESTONES = {
    "下楼到地图 37": 10,
    "真新镇室外地图 0": 24,
    "大木拦路": 74,
    "选宝可梦界面": 104,
    "选好宝可梦": 131,
    "对战开始": 160,
    "对战结束": 207,
    "出研究所": 220,
    "进入地图 12": 238,
}
ROUTE_NAMES = {
    "下楼到地图 37": "downstairs_map_37",
    "真新镇室外地图 0": "pallet_town_outside",
    "大木拦路": "oak_intercepts_on_route_1_approach",
    "选宝可梦界面": "starter_choice_available",
    "选好宝可梦": "bulbasaur_selected_no_nickname",
    "对战开始": "mandatory_rival_battle_start",
    "对战结束": "mandatory_rival_battle_complete",
    "出研究所": "lab_exit_to_pallet",
    "进入地图 12": "route_1_entry",
}


def sha256_of(path: Path) -> str:
    """计算文件字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _route_oracle(route_path: Path) -> tuple[int, dict[str, int]]:
    """从冷启动实验路线读取总步数与里程碑，避免复制时漂移。"""
    route = json.loads(route_path.read_text(encoding="utf-8"))
    milestones = {entry["name"]: entry["oracle_steps"] for entry in route["milestones"]}
    values = {label: milestones[name] for label, name in ROUTE_NAMES.items()}
    total = milestones["route_1_entry"]
    return total, values


def _readout(state: bytes) -> tuple[RamReadout, TaskObservation]:
    """用生产 RAM 读取与 task 感知器读取起点。"""
    import io

    from pyboy import PyBoy

    from pokemon_agent.world.ram import map_settled, read_terrain
    from pokemon_agent.world.screen_text import read_screen_text
    from pokemon_agent.world.task_perception import observe_task

    emulator = PyBoy("assets/rom", window="null", sound_emulated=False)
    try:
        emulator.load_state(io.BytesIO(state))
        emulator.tick(1)
        memory = emulator.memory
        text = read_screen_text(memory)
        terrain = read_terrain(memory) if map_settled(memory) else None
        import_buffer = __import__("io").BytesIO()
        emulator.screen.image.save(import_buffer, format="PNG")
        perceived = observe_task(
            terrain,
            text,
            import_buffer.getvalue(),
            memory=memory,
            rom=Path("assets/rom").read_bytes(),
            closed=False,
        )
        return perceived.ram, perceived.observation
    finally:
        emulator.stop(False)


def build_dataset(
    *,
    dataset_root: Path = DATA_ROOT,
    target_dir: Path | None = None,
    rom: Path = Path("assets/rom"),
    keys_path: Path = KEYS_PATH,
    route_path: Path = ROUTE_PATH,
    validate: bool = True,
) -> Path:
    """生成状态、样本、rubric、coverage 与 revision，不覆盖已存在版本。"""
    output_dir = target_dir or dataset_root / NEW_VERSION
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing dataset: {output_dir}")
    first, second, readouts = generate_pair(rom, keys_path)
    state_hash = hashlib.sha256(first).hexdigest()
    if hashlib.sha256(second).hexdigest() != state_hash or state_hash != EXPECTED_SHA256:
        raise ValueError("卧室存档重复生成哈希不符")

    start = {
        "kind": "state",
        "archive": "",
        "source_state": "states/new_game_bedroom.state",
        "source_sha256": state_hash,
    }
    sample_data = {
        "sample_id": "long_leave_pallet_town",
        "dataset_version": NEW_VERSION,
        "granularity": "run",
        "tier": "long",
        "category": "exploration",
        "start": start,
        "goal": "离开真新镇，一路向北走到镇外。",
        "success_criteria": (
            "人已走出真新镇，来到北边的下一个区域，并且队伍里已经有一只自己的宝可梦。"
        ),
        "max_steps": 720,
        "goals": [],
        "initial_state_hint": "新游戏卧室；尚未离开家。",
        "behavior": (
            "从卧室下楼出门，往北走会被大木拦住带去研究所，选一只宝可梦，与对手对战，然后出镇往北。"
        ),
        "check_id": "leave_pallet_town",
        "k_metric": "pass_at_k",
        "knowledge_exclude_topics": ["map_connections"],
        "rubric": ["decompose_quality", "strategy_switch", "redundant_path"],
        "red_lines": ["R1", "R2", "R3"],
        "split": "val",
    }
    sample = EvalSample.model_validate(sample_data)
    if validate:
        ram, observation = _readout(first)
        validate_start(sample, ram, observation)

    total_steps, milestones = _route_oracle(route_path)
    output_dir.mkdir(parents=True)
    states_dir = output_dir / "states"
    states_dir.mkdir()
    state_path = states_dir / "new_game_bedroom.state"
    state_path.write_bytes(first)
    samples_path = output_dir / "samples.jsonl"
    samples_path.write_text(
        json.dumps(sample_data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    rubric = json.loads((DATA_ROOT / "v20261028_mid" / "rubric.json").read_text(encoding="utf-8"))
    rubric["version"] = NEW_VERSION
    (output_dir / "rubric.json").write_text(
        json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "coverage.md").write_text(
        "# v20261028_long coverage\n\n"
        "| sample_id | tier | granularity | check_id | start | oracle_steps | max_steps |\n"
        "|---|---|---|---|---|---:|---:|\n"
        + (
            "| long_leave_pallet_town | long | run | leave_pallet_town | "
            f"states/new_game_bedroom.state | {total_steps} | 720 |\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    revision: dict[str, Any] = {
        "change": "新增长期开放探索样本：从新游戏卧室起步，离开真新镇",
        "samples": {
            "long_leave_pallet_town": {
                "oracle_steps": total_steps,
                "milestones": milestones,
                "max_steps": 720,
                "start_readout": {
                    "map_id": 38,
                    "position": [3, 6],
                    "party": [],
                    "bag": [],
                    "money": 3000,
                    "D74E": "0x00",
                },
            }
        },
        "source_files": {
            "long_start_keys.json": sha256_of(keys_path),
            "states/new_game_bedroom.state": state_hash,
            "route.json": sha256_of(route_path),
        },
        "cold_start_readouts": readouts,
    }
    (output_dir / "revision.json").write_text(
        json.dumps(revision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if validate:
        validate_tiers([sample])
        check(NEW_VERSION, rule_ids={"leave_pallet_town"})
    return output_dir


def main() -> None:
    """生成长期数据集版本。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DATA_ROOT)
    arguments = parser.parse_args()
    print(build_dataset(dataset_root=arguments.dataset_root))


if __name__ == "__main__":
    main()


__all__ = ["build_dataset", "sha256_of"]
