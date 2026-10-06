"""一帧样本 → task 层执行器会看到的观测。

与 `PyBoyWorld._ram_observe` 同一套解码与渲染（地形字段除外）。
"""

from __future__ import annotations

from pokemon_agent.world import (
    TAKEOVER_SCENES,
    W_IS_IN_BATTLE,
    W_TILEMAP,
    Facts,
    at_start,
    classify_scene,
    layout_field,
    overlay_of,
    read_screen_text,
)
from pokemon_agent.world.interface import ScreenText

from .schemas import ScreenAnswer, ScreenSample


class _Screen:
    """按地址取字节的假内存：只有屏幕缓冲与战斗标志。"""

    def __init__(self, sample: ScreenSample) -> None:
        self._tiles, self._battle = sample.tiles, int(sample.in_battle)

    def __getitem__(self, address: int) -> int:
        if address == W_IS_IN_BATTLE:
            return self._battle
        offset = address - W_TILEMAP
        return self._tiles[offset // 20][offset % 20] if 0 <= offset < 360 else 0


def screen_text(sample: ScreenSample) -> ScreenText:
    """这一帧的屏幕解码。"""
    return read_screen_text(_Screen(sample))


def task_facts(text: ScreenText) -> Facts:
    """task 层 `Facts` 里与屏幕有关的那几项（地形 / 位置 / 地标不在这里测）。"""
    return Facts(
        scene=Facts.Scene.BATTLE if text.in_battle else None,
        overlay=overlay_of(text),
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor or None,
        screen=text.screen,
        **layout_field(text),
    )


def observation_text(facts: Facts) -> str:
    """按 `decide_action.py` 渲染 `$facts` 的同一写法：逐项 `- 键: 值`。"""
    return "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "（无）"


def decoded_answer(text: ScreenText, ram: bytes = b"") -> ScreenAnswer:
    """解码直出：不调模型，字段原样当回答；场合与是否在初态由 world 的分类器给（数量恒为 None）。"""
    scene, start = scene_of(text, ram)
    return ScreenAnswer(
        scene=scene,
        at_start=start,
        overlay=overlay_of(text).value,  # type: ignore[arg-type]
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor,
    )


def scene_of(text: ScreenText, ram: bytes) -> tuple[str, bool | None]:
    """world 的场合与初态（`classify_scene` / `at_start`）；常规场合的初态为 None。"""
    scene = classify_scene(text, _Wram(ram))
    return scene.value, (at_start(text, scene) if scene in TAKEOVER_SCENES else None)


class _Wram:
    """整块 WRAM 快照（0xC000 起）→ 按绝对地址取字节；没有快照（v1 样本）时一律 0。"""

    def __init__(self, ram: bytes) -> None:
        self._ram = ram

    def __getitem__(self, address: int) -> int:
        return self._ram[address - 0xC000] if self._ram else 0


def bucket(text: ScreenText) -> str:
    """按解码结果把帧分桶，报表按桶看（不用人工类别，两批样本都能分）。"""
    if text.quantity_box:
        return "数量框"
    if text.has_cursor:
        return "选单" if text.covered and text.options else "选单(解码切不全)"
    if text.strict_dialog:
        return "纯对话"
    if text.dialog_text:
        return "对话+其他框"
    return "无叠加"


__all__ = ["bucket", "decoded_answer", "observation_text", "scene_of", "screen_text", "task_facts"]
