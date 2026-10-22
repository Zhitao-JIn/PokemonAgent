"""task 档单帧 RAM 观测装配；地图不稳定时省略位置与地形。"""

from .battle_status import read_battle_status
from .frame_encoding import png_data_uri
from .interface import Facts, Memory, ScreenText, TaskObservation, TaskPerceived, TerrainMap
from .readout import read_readout
from .scene import classify_scene
from .screen_text import overlay_of
from .scripts.scenes import takeover_view


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
    battle = read_battle_status(mem)
    facts = Facts(
        scene=Facts.Scene.BATTLE if text.in_battle else None,
        overlay=overlay,
        facing=terrain.facing or "" if terrain is not None else "",
        landmarks=terrain.landmarks() if terrain is not None else [],
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor or None,
        map_id=terrain.map_id if terrain is not None else None,
        screen=text.screen,
        neighbor_cells=terrain.neighbors() if terrain is not None else {},
        cells=list(terrain.cells) if terrain is not None else [],
        option_grid=text.option_grid,
        cursor_cell=text.cursor_cell,
        option_annotations=text.option_details,
        battle_status=battle,
        terrain_visible=terrain is not None and not text.screen,
    )
    return TaskPerceived(
        observation=TaskObservation(
            step=0,
            place=terrain.place() if terrain is not None else None,
            facts=facts,
            done=closed,
            scene=scene,
            menu_decode_complete=text.covered,
            takeover=takeover_view(scene, text, mem, rom),
        ),
        frame_png=png_data_uri(png),
        ram=read_readout(mem, text, text_source="decode"),
    )
