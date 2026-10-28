"""从 ROM 冷启动并按固定按键序列生成长期卧室起点。"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyboy import PyBoy

from pokemon_agent.world.ram import W_CUR_MAP, W_X_COORD, W_Y_COORD
from pokemon_agent.world.readout import read_bag, read_money, read_party
from pokemon_agent.world.scene import classify_scene
from pokemon_agent.world.screen_text import read_screen_text

EXPECTED_SHA256 = "95b2cabd5b83d7d6922f4504f6602bd4d121de146b34c1a59db13c8a8a977158"
KEYS_PATH = Path(__file__).with_name("long_start_keys.json")


def sha256_bytes(content: bytes) -> str:
    """计算存档字节的 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def _snapshot(emulator: PyBoy) -> dict[str, Any]:
    """读取实验用于确认终点的场景与 RAM 字段。"""
    memory = emulator.memory
    return {
        "scene": classify_scene(read_screen_text(memory), memory).value,
        "map_id": int(memory[W_CUR_MAP]),
        "x": int(memory[W_X_COORD]),
        "y": int(memory[W_Y_COORD]),
        "party": read_party(memory),
        "bag": read_bag(memory),
        "money": read_money(memory),
        "D74E": int(memory[0xD74E]),
    }


def generate_state(rom: Path, keys: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """不加载 state，按实验中的冷启动流程生成一份卧室存档。"""
    emulator = PyBoy(str(rom), window="null", sound_emulated=False)
    emulator.set_emulation_speed(0)
    frame = 0

    def tick(count: int) -> None:
        nonlocal frame
        for _ in range(count):
            emulator.tick(1)
        frame += count

    def press(key: str, held_frames: int) -> None:
        emulator.button(key, delay=held_frames)
        tick(held_frames)

    def wait_for(predicate: Callable[[], bool], limit: int) -> None:
        waited = 0
        while not predicate() and waited < limit:
            tick(10)
            waited += 10

    def scene() -> str:
        return classify_scene(read_screen_text(emulator.memory), emulator.memory).value

    try:
        tick(keys["startup_wait_frames"])
        sequence = keys["keys"]
        press(sequence[0]["key"], sequence[0]["held_frames"])
        wait_for(lambda: "NEW GAME" in read_screen_text(emulator.memory).options, 1800)
        if "NEW GAME" not in read_screen_text(emulator.memory).options:
            raise RuntimeError("按 START 后标题菜单没有 NEW GAME")
        press(sequence[1]["key"], sequence[1]["held_frames"])
        wait_for(lambda: scene() == "dialog", keys["wait_limit_frames"])
        tick(keys["post_key_wait_frames"])

        for name in ("RED", "BLUE"):
            for _ in range(40):
                observed = _snapshot(emulator)
                if name in read_screen_text(emulator.memory).options:
                    break
                if observed["scene"] != "dialog":
                    raise RuntimeError(f"等待 {name} 名字选项时场景异常：{observed['scene']}")
                press("a", 10)
                wait_for(lambda: scene() != "transition", keys["wait_limit_frames"])
                tick(keys["post_key_wait_frames"])
            else:
                raise RuntimeError(f"没有到达 {name} 名字选项")
            if name not in read_screen_text(emulator.memory).options:
                raise RuntimeError(f"默认名字选项 {name} 不存在")
            press("down", 10)
            if read_screen_text(emulator.memory).cursor != name:
                raise RuntimeError(f"默认名字光标没有选中 {name}")
            press("a", 10)
            wait_for(lambda: scene() != "transition", keys["wait_limit_frames"])
            tick(keys["post_key_wait_frames"])

        for _ in range(50):
            current_scene = scene()
            if current_scene == "walk":
                break
            if current_scene == "dialog":
                press("a", 10)
                wait_for(lambda: scene() != "transition", keys["wait_limit_frames"])
                tick(keys["post_key_wait_frames"])
            else:
                tick(30)
        else:
            raise RuntimeError("冷启动没有到达可行走地图")

        if len(sequence) != 33:
            raise ValueError(f"按键序列应有 33 次按键，实际 {len(sequence)}")
        state = io.BytesIO()
        emulator.save_state(state)
        return state.getvalue(), {**_snapshot(emulator), "frames": frame}
    finally:
        emulator.stop(False)


def generate_pair(
    rom: Path, keys_path: Path = KEYS_PATH
) -> tuple[bytes, bytes, list[dict[str, Any]]]:
    """在同一进程中连续两次从 ROM 冷启动并返回结果。"""
    keys = json.loads(keys_path.read_text(encoding="utf-8"))
    first, first_readout = generate_state(rom, keys)
    second, second_readout = generate_state(rom, keys)
    digests = [sha256_bytes(first), sha256_bytes(second)]
    if digests[0] != digests[1] or digests[0] != EXPECTED_SHA256:
        raise ValueError(f"冷启动存档哈希不符：{digests}，预期 {EXPECTED_SHA256}")
    return first, second, [first_readout, second_readout]


__all__ = ["EXPECTED_SHA256", "generate_pair", "generate_state", "sha256_bytes"]
