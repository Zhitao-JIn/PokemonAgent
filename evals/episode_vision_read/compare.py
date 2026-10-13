"""人工标注的适用字段与纯比较；不依赖 DeepEval。"""

from typing import Any

from evals.dataset.frames.schemas import ScreenLabel, ScreenSample
from evals.dataset.frames.snapshot import SnapshotMemory, snapshot_of
from evals.decode.compare import Verdict
from pokemon_agent.world import Facts
from pokemon_agent.world.ram import OVERWORLD_TILESET, W_CUR_MAP_TILESET

S = Facts.Scene
SCENE_TRUTH: dict[str, Facts.Scene] = {
    "battle": S.BATTLE,
    "battle_menu": S.BATTLE,
    "battle_switch": S.BATTLE,
    "shop_items": S.SHOP,
    "shop": S.INDOOR,
    "start_menu": S.MENU,
    "bag": S.MENU,
    "party": S.MENU,
    "pokemon_info": S.MENU,
    "naming": S.NAMING,
    "transition": S.TRANSITION,
}
ON_MAP = ("walk", "dialog")


def _scene_truth(label: ScreenLabel, memory: SnapshotMemory | None) -> Facts.Scene | None:
    """标注场合转换为 episode 场景；无从判时返回 None。"""
    if label.scene in ON_MAP:
        if memory is None:
            return None
        return S.FIELD if memory[W_CUR_MAP_TILESET] == OVERWORLD_TILESET else S.INDOOR
    return SCENE_TRUTH.get(label.scene)


def truth_fields(sample: ScreenSample) -> dict[str, Any]:
    """只给可判字段；overlay 与 parsed 始终适用。"""
    memory = snapshot_of(sample)[1] if sample.wram else None
    label = sample.label
    truth: dict[str, Any] = {"overlay": label.overlay, "parsed": True}
    scene = _scene_truth(label, memory)
    if scene is not None:
        truth["scene"] = scene
    if label.overlay == "dialog":
        truth["dialog_text"] = label.dialog_text
    if label.overlay == "choice" and label.options:
        truth["options"] = label.options
    if label.overlay == "choice" and label.cursor:
        truth["cursor"] = label.cursor
    return truth


def _flat(text: str) -> str:
    """只规整换行与连续空白。"""
    return " ".join(text.split())


def field_verdict(got: dict[str, Any], want: dict[str, Any], key: str) -> Verdict:
    """未标为 N；解析失败时适用字段均为 I，否则沿用旧相等与空白规则。"""
    if key not in want:
        return Verdict(value="N", reason="这一帧无从判此字段")
    if not got["parsed"]:
        return Verdict(value="I", reason=got["failure"])
    if key == "parsed":
        return Verdict(value="C", reason="解析成功")
    actual, expected = got[key], want[key]
    if key in {"dialog_text", "cursor"}:
        actual, expected = _flat(actual or ""), _flat(expected)
    if key == "options":
        actual, expected = [_flat(text) for text in actual], [_flat(text) for text in expected]
    return Verdict(
        value="C" if actual == expected else "I",
        reason=f"{actual!r} ≠ {expected!r}" if actual != expected else "符合标注",
    )
