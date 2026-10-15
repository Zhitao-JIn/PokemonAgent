"""episode 档的一帧感知：截图 + 内存 → `Perceived`（只问一次视觉模型）。"""

from __future__ import annotations

from pokemon_agent.world import VisionProvider

from .frame_encoding import png_data_uri
from .interface import Facts, Memory, Observation, Perceived, ScreenState, ScreenText, TerrainMap
from .interface.domain import terrain_legend
from .prompts import PromptTemplate
from .ram import map_settled, read_terrain
from .readout import read_readout
from .screen_text import layout_field, overlay_of, read_screen_text
from .task_perception import _battle_fields
from .visual_perception import parse_screen, perceive_visual


def _checked_overlay(vision: Facts.Overlay, text: ScreenText) -> Facts.Overlay:
    """看档路径的叠加层：视觉说是对话框，还得屏幕解码认得是严格的对话帧，否则按解码推。"""
    if vision is Facts.Overlay.DIALOG and not text.strict_dialog:
        return overlay_of(text)
    return vision


def _status_line(s: ScreenState, cursor: str = "") -> str:
    """给大脑读的自然语言状态。"""
    where = {
        Facts.Scene.FIELD: "你在野外",
        Facts.Scene.INDOOR: "你在室内",
        Facts.Scene.BATTLE: "你在战斗中",
        Facts.Scene.MENU: "你在菜单里",
        Facts.Scene.SHOP: "你在商店",
        Facts.Scene.TRANSITION: "画面正在切换",
        Facts.Scene.NAMING: "你在起名字",
        Facts.Scene.MAP_VIEW: "你在看地区总览地图",
    }[s.scene]
    bits = [where + "。"]
    if s.overlay is Facts.Overlay.DIALOG and s.dialog_text:
        bits.append(f"对话框：「{s.dialog_text}」")
    elif s.overlay is Facts.Overlay.CHOICE and s.options:
        cur = f"，光标在 {cursor}" if cursor else "，光标读不出"
        bits.append(f"可选项：{'/ '.join(s.options)}{cur}")
    return "".join(bits)


def perceive_frame(
    png: bytes,
    memory: Memory,
    *,
    template: PromptTemplate,
    vision: VisionProvider,
    closed: bool = False,
) -> Perceived:
    """一帧截图 + 同一时刻的内存 → episode 档观测（只问一次视觉模型，不重试）。"""
    # 步骤 1。
    terrain = read_terrain(memory) if map_settled(memory) else None

    # 步骤 2：问一次视觉模型（屏幕解码也读一遍，给整屏原样与叠加层核对用）。
    ram_text = read_screen_text(memory)
    prompt = template.render(
        known_map=terrain.render() if terrain is not None else "", terrain_legend=terrain_legend()
    )
    visual = perceive_visual(png, prompt=prompt, vision=vision)
    screen, call = visual.screen, visual.call

    # 步骤 3：把"内存读出来的地形"和"模型读出来的屏幕"拼成一份观测。
    overlay, text = _checked_overlay(screen.overlay, ram_text), screen.dialog_text.strip()

    if overlay is Facts.Overlay.DIALOG and not text:
        overlay = Facts.Overlay.NONE

    obs = _observation(screen, ram_text, memory, terrain, overlay, closed)
    ram = read_readout(memory, ram_text, text_source="vlm")
    return Perceived(observation=obs, calls=[call], frame_png=png_data_uri(png), ram=ram)


def _observation(
    screen: ScreenState,
    ram_text: ScreenText,
    memory: Memory,
    terrain: TerrainMap | None,
    overlay: Facts.Overlay,
    closed: bool,
) -> Observation:
    """将同帧材料装配成观测；不稳定地图的地点与地形字段为空。"""
    landmarks = terrain.landmarks() if terrain is not None else []

    text = screen.dialog_text.strip()
    facts = Facts(
        scene=screen.scene,
        overlay=overlay,
        where=terrain.place().render() if terrain is not None else "",
        facing=terrain.facing or "" if terrain is not None else "",
        neighbors=terrain.render_neighbors() if terrain is not None else "",
        landmarks=landmarks,
        dialog_text=text,
        options=screen.options,
        cursor=screen.cursor or "",
        overview=screen.overview,
        walk_map=terrain.render() if terrain is not None else "",
        map_id=terrain.map_id if terrain is not None else None,
        screen=ram_text.screen,
        **{**screen.fields, **_battle_fields(memory)},
        **layout_field(ram_text),
    )

    return Observation(
        step=0,
        place=terrain.place() if terrain is not None else None,
        status=_status_line(screen, facts.cursor or ""),
        facts=facts,
        done=closed,
    )


__all__ = ["parse_screen", "perceive_frame"]
