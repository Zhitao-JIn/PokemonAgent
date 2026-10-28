"""从父版本存档确定性派生中期评测起点。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pokemon_agent.world.ram import W_BATTLE_MON_HP, W_TILEMAP

M3_OUTPUT = "m3_bulbasaur_half_hp_battle.state"
M3_HUD_EDITS = (
    # wTileMap rows 9 and 10: 12/25 HP bar and numerator digits.
    (W_TILEMAP + 9 * 20 + 14, 0x6B, 0x6A),
    (W_TILEMAP + 9 * 20 + 15, 0x6B, 0x63),
    (W_TILEMAP + 9 * 20 + 16, 0x6B, 0x63),
    (W_TILEMAP + 9 * 20 + 17, 0x6B, 0x63),
    (W_TILEMAP + 10 * 20 + 12, 0xF8, 0xF7),
    (W_TILEMAP + 10 * 20 + 13, 0xFB, 0xF8),
)

PARENT_STATES = {
    "knowledge_pokemon_center_enter.state": (
        "dff9d4674faf6ee5893feccda6b72fb9f491a814fdd241150e314249aa0dae3a"
    ),
    "knowledge_catch_weaken_target.state": (
        "7da2bb185f7469b0c9d148fb28f1c01cd897d0458da06842b3d2e0aa482287ee"
    ),
    "knowledge_shop_interaction.state": (
        "bddd2bdf21a73bc25e6af57f5ed1d4262625afef30532a15b76b81421f927fe3"
    ),
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_m2(memory: object) -> list[dict[str, int]]:
    return [_set_byte(memory, 0xD16D, 0x19, 0x0C)]


def derive_m3(memory: object) -> list[dict[str, int]]:
    edits = [_set_byte(memory, 0xD16D, 0x19, 0x0C)]
    before_hi, before_lo = memory[W_BATTLE_MON_HP], memory[W_BATTLE_MON_HP + 1]
    if (before_hi, before_lo) != (0x00, 0x19):
        raise ValueError(f"M3 cached battle HP expected 00 19, got {before_hi:02X} {before_lo:02X}")
    memory[W_BATTLE_MON_HP] = 0x00
    memory[W_BATTLE_MON_HP + 1] = 0x0C
    edits.extend(
        [
            {"address": W_BATTLE_MON_HP, "before": before_hi, "after": memory[W_BATTLE_MON_HP]},
            {
                "address": W_BATTLE_MON_HP + 1,
                "before": before_lo,
                "after": memory[W_BATTLE_MON_HP + 1],
            },
        ]
    )
    for address, expected, value in M3_HUD_EDITS:
        edits.append(_set_byte(memory, address, expected, value))
    return edits


def m3_hp_consistency_issues(
    party_hp: int,
    battle_hp: int,
    screen_text: str,
    hud_tiles: list[int],
    *,
    max_hp: int = 25,
) -> list[str]:
    """Return mismatches among M3 party/cache HP, decoded HUD text and its six bar tiles."""
    issues: list[str] = []
    if party_hp != battle_hp:
        issues.append("party and battle cache HP differ")
    fractions = re.findall(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", screen_text)
    if (str(party_hp), str(max_hp)) not in fractions:
        issues.append("decoded HUD HP differs")
    expected_bar = m3_hud_bar_tiles(party_hp, max_hp)
    if hud_tiles != expected_bar:
        issues.append("HUD bar tiles differ")
    return issues


def m3_hud_bar_tiles(hp: int, max_hp: int = 25) -> list[int]:
    """Map HP to the six bar tiles, matching the game's observed 8-pixel segments."""
    if not 0 <= hp <= max_hp or max_hp <= 0:
        raise ValueError(f"invalid HP {hp}/{max_hp}")
    filled_pixels = hp * 48 // max_hp
    full_tiles, partial_pixels = divmod(filled_pixels, 8)
    tiles = [0x6B] * full_tiles
    if partial_pixels:
        tiles.append(0x63 + partial_pixels)
    return tiles[:6] + [0x63] * max(0, 6 - len(tiles))


def write_derived_m3_state(rom: Path, parent_dir: Path, target_dir: Path) -> dict[str, object]:
    """Explicitly regenerate only the M3 state, replacing that exact output file."""
    from pyboy import PyBoy

    source = parent_dir / "states" / "knowledge_catch_weaken_target.state"
    _verify_source(source, source.name)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / M3_OUTPUT
    emulator = PyBoy(str(rom), window="null", sound_emulated=False)
    try:
        with source.open("rb") as stream:
            emulator.load_state(stream)
        edits = derive_m3(emulator.memory)
        with destination.open("wb") as stream:
            emulator.save_state(stream)
    finally:
        emulator.stop(save=False)
    return {
        "source_sha256": sha256_of(source),
        "edits": edits,
        "sha256": sha256_of(destination),
    }


def regenerate_m3_dataset(
    parent_dir: Path,
    output_dir: Path,
    *,
    rom: Path,
    perceive_state: Callable[[Path], tuple[Any, Any, int, list[int]]],
) -> dict[str, object]:
    """Replace the single M3 start and refresh only its sample and revision hashes."""
    from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
    from evals.agent_short_goal_run.dataset.schemas import EvalSample

    states_dir = output_dir / "states"
    state_path = states_dir / M3_OUTPUT
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    other_hashes = {
        path.name: sha256_of(path)
        for path in states_dir.iterdir()
        if path.is_file() and path.name != M3_OUTPUT
    }
    record = write_derived_m3_state(rom, parent_dir, states_dir)
    if any(sha256_of(states_dir / name) != digest for name, digest in other_hashes.items()):
        raise OSError("M3 regeneration changed another dataset state")

    sample_path = output_dir / "samples.jsonl"
    rows = sample_path.read_text(encoding="utf-8").splitlines()
    m3_row = next(json.loads(line) for line in rows if '"mid_catch_then_heal"' in line)
    sample = EvalSample.model_validate(m3_row)
    ram, observation, _event_flags, hud = perceive_state(state_path)
    validate_start(sample, ram, observation)
    assert observation.takeover is not None
    issues = m3_hp_consistency_issues(
        ram.party[0].hp, observation.takeover.mine.hp, observation.facts.screen, hud
    )
    if issues:
        raise ValueError(f"regenerated M3 HP/HUD inconsistency: {', '.join(issues)}")

    updated_rows = []
    found = False
    for line in rows:
        data = json.loads(line)
        if data["sample_id"] == "mid_catch_then_heal":
            data["start"]["source_sha256"] = record["sha256"]
            line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            found = True
        updated_rows.append(line)
    if not found:
        raise ValueError("M3 sample missing from samples.jsonl")
    sample_path.write_text("\n".join(updated_rows) + "\n", encoding="utf-8", newline="\n")

    revision_path = output_dir / "revision.json"
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    sample_record = revision["samples"]["mid_catch_then_heal"]
    sample_record["state_sha256"] = record["sha256"]
    sample_record["ram_edits"] = [
        _edit_json(edit) for edit in record["edits"] if edit["address"] >= 0xD000
    ]
    sample_record["screen_edits"] = [
        _screen_edit_json(edit)
        for edit in record["edits"]
        if 0xC3A0 <= edit["address"] < 0xC3A0 + 360
    ]
    revision["source_files"][f"states/{M3_OUTPUT}"] = record["sha256"]
    revision_path.write_text(
        json.dumps(revision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return record


def _edit_json(edit: dict[str, int]) -> dict[str, str]:
    return {
        "address": f"0x{edit['address']:04X}",
        "before": f"0x{edit['before']:02X}",
        "after": f"0x{edit['after']:02X}",
    }


def _screen_edit_json(edit: dict[str, int]) -> dict[str, str | int]:
    offset = edit["address"] - 0xC3A0
    return {
        **_edit_json(edit),
        "row": offset // 20,
        "column": offset % 20,
    }


def derive_m5(memory: object) -> list[dict[str, int]]:
    return [_set_byte(memory, 0xD19B, 0x00, 0x08)]


def _set_byte(memory: object, address: int, expected: int, value: int) -> dict[str, int]:
    before = memory[address]
    if before != expected:
        raise ValueError(f"expected RAM 0x{address:04X}={expected:02X}, got {before:02X}")
    memory[address] = value
    return {"address": address, "before": before, "after": memory[address]}


def write_derived_starts(rom: Path, parent_dir: Path, target_dir: Path) -> dict[str, dict]:
    """复制 M1/M4，模拟器改 RAM 派生 M2/M3/M5；绝不覆盖已有目标。"""
    from pyboy import PyBoy

    if target_dir.exists():
        raise FileExistsError(f"refusing to overwrite derived starts: {target_dir}")
    target_dir.mkdir(parents=True)
    states = parent_dir / "states"
    records: dict[str, dict] = {}
    for filename in ("knowledge_pokemon_center_enter.state", "knowledge_shop_interaction.state"):
        source = states / filename
        _verify_source(source, filename)
        destination = target_dir / filename
        shutil.copyfile(source, destination)
        if sha256_of(source) != sha256_of(destination):
            raise OSError(f"state copy hash mismatch: {filename}")
        records[filename] = {
            "source_sha256": sha256_of(source),
            "edits": [],
            "sha256": sha256_of(destination),
        }

    derivations = (
        ("knowledge_pokemon_center_enter.state", "m2_bulbasaur_half_hp.state", derive_m2),
        ("knowledge_catch_weaken_target.state", "m3_bulbasaur_half_hp_battle.state", derive_m3),
        ("knowledge_pokemon_center_enter.state", "m5_pidgey_poisoned.state", derive_m5),
    )
    for source_name, target_name, transform in derivations:
        source = states / source_name
        _verify_source(source, source_name)
        emulator = PyBoy(str(rom), window="null", sound_emulated=False)
        try:
            with source.open("rb") as stream:
                emulator.load_state(stream)
            edits = transform(emulator.memory)
            destination = target_dir / target_name
            with destination.open("xb") as stream:
                emulator.save_state(stream)
        finally:
            emulator.stop(save=False)
        records[target_name] = {
            "source_sha256": sha256_of(source),
            "edits": edits,
            "sha256": sha256_of(destination),
        }
    return records


def _verify_source(source: Path, filename: str) -> None:
    expected = PARENT_STATES[filename]
    actual = sha256_of(source)
    if actual != expected:
        raise ValueError(f"source state hash mismatch for {filename}: {actual}")


__all__ = [
    "derive_m2",
    "derive_m3",
    "derive_m5",
    "m3_hp_consistency_issues",
    "m3_hud_bar_tiles",
    "write_derived_m3_state",
    "write_derived_starts",
]
