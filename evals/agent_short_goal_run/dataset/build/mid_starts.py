"""从父版本存档确定性派生中期评测起点。"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from pokemon_agent.world.ram import W_BATTLE_MON_HP

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
    return edits


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


__all__ = ["derive_m2", "derive_m3", "derive_m5", "write_derived_starts"]
