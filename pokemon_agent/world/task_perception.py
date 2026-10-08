"""task 档单帧 RAM 观测装配；地图不稳定时省略位置与地形。"""

from .interface import Facts, Memory, ScreenText, TaskObservation, TaskPerceived, TerrainMap
from .perceive_frame import _battle_fields
from .readout import read_readout
from .scene import classify_scene
from .screen_text import layout_field, overlay_of
from .scripts.scenes import takeover_view
from .visual_perception import _png_data_uri


def _ram_status(terrain: TerrainMap | None, text: ScreenText) -> str:
    """纯 RAM 观测的状态行：位置、朝向，加上屏幕文字能确定的对话 / 选项 / 光标。"""
    if terrain is None:
        return "（这一帧只读了内存）地图尚未稳定。"
    facing = f"，朝向 {terrain.facing}" if terrain.facing else ""
    bits = [f"（这一帧只读了内存）{terrain.place().render()}{facing}"]
    if text.in_battle:
        bits.append("战斗中")
    if text.dialog_text:
        bits.append(f"对话框：「{text.dialog_text}」")
    if text.options:
        bits.append(f"可选项：{'/ '.join(text.options)}，光标在 {text.cursor}")
    return "。".join(bits)


def observe_task(
    terrain: TerrainMap | None,
    text: ScreenText,
    png: bytes,
    *,
    memory: Memory,
    rom: bytes,
    closed: bool,
) -> TaskPerceived:
    """只读内存的观测——**这一档不调视觉模型**。"""
    overlay = overlay_of(text)
    mem = memory
    scene = classify_scene(text, mem)
    facts = Facts(
        scene=Facts.Scene.BATTLE if text.in_battle else None,
        overlay=overlay,
        where=terrain.place().render() if terrain is not None else "",
        facing=terrain.facing or "" if terrain is not None else "",
        neighbors=terrain.render_neighbors() if terrain is not None else "",
        landmarks=terrain.landmarks() if terrain is not None else [],
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor or None,
        walk_map=terrain.render() if terrain is not None and not text.screen else "",
        map_id=terrain.map_id if terrain is not None else None,
        screen=text.screen,
        **_battle_fields(mem),
        **layout_field(text),
    )
    return TaskPerceived(
        observation=TaskObservation(
            step=0,
            place=terrain.place() if terrain is not None else None,
            status=_ram_status(terrain, text),
            facts=facts,
            done=closed,
            perceived=False,
            scene=scene,
            menu_decode_complete=text.covered,
            takeover=takeover_view(scene, text, mem, rom),
        ),
        frame_png=_png_data_uri(png),
        ram=read_readout(mem, text, text_source="decode"),
    )
