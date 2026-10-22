"""一帧样本 → task 层执行器会看到的观测。

与生产世界 `_ram_observe` 同一套解码与渲染（地形字段除外）。
"""

from __future__ import annotations

from pokemon_agent.world import (
    SCRIPT_ONLY_SCENES,
    W_IS_IN_BATTLE,
    W_TILEMAP,
    Facts,
    at_start,
    classify_scene,
    overlay_of,
    read_screen_text,
)
from pokemon_agent.world.interface import ScreenText

from ..schemas import ScreenAnswer, ScreenSample


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


_EXTRA_ORDER = ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp")
"""旧 `Facts._EXTRA_ORDER` 的冻结副本：重放历史样本时保持原有行序。"""


def _render_layout(text: ScreenText) -> str:
    """旧 `ScreenText.render_layout()` 的冻结副本：构建历史样本时逐字节对齐。"""
    if not text.option_grid or text.cursor_cell is None:
        return ""
    rows, cols = len(text.option_grid), max(len(row) for row in text.option_grid)
    r, c = text.cursor_cell
    if cols == 1:
        head = f"竖排 {rows} 项，光标在第 {r + 1} 项；上/下 移动光标"
    elif rows == 1:
        head = f"横排 {cols} 项，光标在第 {c + 1} 项；左/右 移动光标"
    else:
        head = f"{rows} 行 × {cols} 列，光标在第 {r + 1} 行第 {c + 1} 列；上/下 换行，左/右 换列"
    lines = [
        "  ".join(("▶" if (i, j) == text.cursor_cell else " ") + item for j, item in enumerate(row))
        for i, row in enumerate(text.option_grid)
    ]
    return head + "\n" + "\n".join(lines)


def _render_details(text: ScreenText) -> str:
    """旧 `ScreenText.render_details()` 的冻结副本：只读结构化选项与附注。"""
    pairs = zip(text.options, text.option_details, strict=False)
    return " / ".join(f"{option} {detail}" for option, detail in pairs if detail)


def _layout_fields(text: ScreenText) -> dict[str, str]:
    """旧 `layout_field()` 的冻结副本：排布与附注作为历史样本的两个文本键。"""
    fields: dict[str, str] = {}
    layout = _render_layout(text)
    if layout:
        fields["option_layout"] = layout
    details = _render_details(text)
    if details:
        fields["option_details"] = details
    return fields


def task_facts(text: ScreenText) -> Facts:
    """task 层 `Facts` 里与屏幕有关的那几项（地形 / 位置 / 地标不在这里测）。"""
    return Facts(
        scene=Facts.Scene.BATTLE if text.in_battle else None,
        overlay=overlay_of(text),
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor or None,
        screen=text.screen,
        **_layout_fields(text),
    )


def _retired(facts: Facts, name: str) -> str:
    """旧文本键只从 extra 读回，不在新观测里重新生成。"""
    value = getattr(facts, name, "")
    return value if isinstance(value, str) else ""


def _facts_items(facts: Facts) -> list[tuple[str, str]]:
    """旧 `Facts.items()` 的冻结副本：重放历史样本的 `- key: value` 行序。"""
    entries: list[tuple[str, str]] = []
    if facts.scene is not None:
        entries.append(("scene", facts.scene.value))
    if facts.overlay is not None:
        entries.append(("overlay", facts.overlay.value))
    where = _retired(facts, "where")
    if where:
        entries.append(("where", where))
    if facts.map_id is not None:
        entries.append(("map_id", str(facts.map_id)))
    if facts.facing:
        entries.append(("facing", facts.facing))
    neighbors = _retired(facts, "neighbors")
    if neighbors:
        entries.append(("neighbors", neighbors))
    if facts.landmarks:
        entries.append(
            ("landmarks", "; ".join(f"{m.kind} x={m.x} y={m.y}" for m in facts.landmarks))
        )
    if facts.dialog_text:
        entries.append(("dialog_text", facts.dialog_text))
    if facts.options:
        entries.append(("options", " / ".join(facts.options)))
    if facts.cursor:
        entries.append(("cursor", facts.cursor))
    extra = facts.model_extra or {}
    seen: set[str] = set()
    for key in _EXTRA_ORDER:
        if key in extra and extra[key] not in (None, ""):
            entries.append((key, str(extra[key])))
            seen.add(key)
    for key in sorted(extra):
        if key in seen or key in {"where", "neighbors", "walk_map"} or extra[key] in (None, ""):
            continue
        entries.append((key, str(extra[key])))
    walk_map = _retired(facts, "walk_map")
    if walk_map:
        entries.append(("walk_map", walk_map))
    if facts.screen:
        entries.append(("screen", "\n" + facts.screen))
    return entries


def observation_text(facts: Facts) -> str:
    """按 `decide_action.py` 渲染 `$facts` 的同一写法：逐项 `- 键: 值`。"""
    return "\n".join(f"- {k}: {v}" for k, v in _facts_items(facts)) or "（无）"


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
    """world 的场合与初态（`classify_scene` / `at_start`）；开放按键的场合的初态为 None。"""
    scene = classify_scene(text, _Wram(ram))
    return scene.value, (at_start(text, scene) if scene in SCRIPT_ONLY_SCENES else None)


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
