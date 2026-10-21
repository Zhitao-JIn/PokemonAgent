"""单帧装配：地图不稳定时省略位置与地形，稳定时逐字段对应素材。"""

from __future__ import annotations

from pokemon_agent.world import Facts, ScreenText, TaskScene, TerrainMap
from pokemon_agent.world.frame_encoding import png_data_uri
from pokemon_agent.world.ram import (
    NAME_END,
    W_BATTLE_MON_HP,
    W_BATTLE_MON_LEVEL,
    W_BATTLE_MON_MAX_HP,
    W_BATTLE_MON_NICK,
    W_BATTLE_MON_STATUS,
    W_ENEMY_MON_HP,
    W_ENEMY_MON_LEVEL,
    W_ENEMY_MON_MAX_HP,
    W_ENEMY_MON_NICK,
    W_ENEMY_MON_STATUS,
)
from pokemon_agent.world.screen_text import CHARMAP, W_IS_IN_BATTLE
from pokemon_agent.world.task_perception import observe_task

PNG = b"\x89PNG\r\n\x1a\nfake"
TILE = {text: tile for tile, text in CHARMAP.items()}
SHOP_SCREEN = "┌─MONEY─┐\n▶BUY  SELL  QUIT"


class Mem:
    """字典式内存：未写地址读 0。"""

    def __init__(self, values: dict[int, int] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, address: int) -> int:
        return self._values.get(address, 0)


def _terrain() -> TerrainMap:
    """九行全 `#`、地图 12、玩家 (13,8)、朝北。"""
    return TerrainMap(
        cells=["##########"] * 9,
        map_id=12,
        player_x=13,
        player_y=8,
        facing="north",
        ambiguous_cells=0,
    )


def _names(address: int, text: str) -> dict[int, int]:
    return {address + offset: TILE[character] for offset, character in enumerate(text)}


def test_unsettled_map_omits_location_and_terrain() -> None:
    observation = observe_task(
        None, ScreenText(), PNG, memory=Mem(), rom=b"", closed=False
    ).observation

    assert observation.place is None
    assert observation.done is False
    assert observation.facts.where == ""
    assert observation.facts.facing == ""
    assert observation.facts.neighbors == ""
    assert observation.facts.walk_map == ""
    assert observation.facts.map_id is None
    assert observation.facts.landmarks == []
    assert observation.status == "（这一帧只读了内存）地图尚未稳定。"


def test_task_perception_assembles_location_dialog_and_closed() -> None:
    text = ScreenText(dialog_text="你好！", options=["YES", "NO"], cursor="YES")

    observation = observe_task(
        _terrain(), text, PNG, memory=Mem(), rom=b"", closed=True
    ).observation

    assert observation.place.model_dump() == {"map_id": 12, "x": 13, "y": 8}
    assert observation.done is True
    assert observation.facts.where == "全局坐标 地图12 x=13 y=8"
    assert observation.facts.facing == "north"
    assert observation.facts.neighbors == "北 # 南 # 西 # 东 #"
    assert observation.facts.walk_map == _terrain().render()
    assert observation.facts.map_id == 12
    assert observation.facts.landmarks == []
    assert observation.facts.dialog_text == "你好！"
    assert observation.facts.options == ["YES", "NO"]
    assert observation.facts.cursor == "YES"
    assert observation.status == (
        "（这一帧只读了内存）全局坐标 地图12 x=13 y=8，朝向 north。"
        "对话框：「你好！」。可选项：YES/ NO，光标在 YES"
    )


def test_task_perception_wires_frame_and_decoded_readout() -> None:
    text = ScreenText(dialog_text="你好！", options=["YES", "NO"], cursor="YES")

    perceived = observe_task(_terrain(), text, PNG, memory=Mem(), rom=b"", closed=False)

    assert perceived.frame_png == png_data_uri(PNG)
    assert perceived.ram.text_source == "decode"
    assert perceived.ram.decoded.dialog_text == "你好！"
    assert perceived.ram.decoded.options == ["YES", "NO"]
    assert perceived.ram.decoded.cursor == "YES"


def test_task_perception_assembles_shop_items_view() -> None:
    rom = bytearray(0x5000)
    rom[0x4608 + 3 * 3 : 0x4608 + 3 * 3 + 3] = b"\x00\x02\x00"
    rom[0x4608 + 4 * 3 : 0x4608 + 4 * 3 + 3] = b"\x00\x03\x00"
    memory = Mem({0xCF7B: 2, 0xCF7C: 4, 0xCF7D: 5, 0xCF7E: 0xFF})
    text = ScreenText(
        screen=SHOP_SCREEN, options=["BUY", "SELL", "QUIT"], cursor="BUY", has_cursor=True
    )

    observation = observe_task(
        _terrain(), text, PNG, memory=memory, rom=bytes(rom), closed=False
    ).observation

    assert observation.scene is TaskScene.SHOP_ITEMS
    assert observation.takeover.model_dump() == {
        "kind": "shop_items",
        "items": [{"name": "POKé BALL", "price": 200}, {"name": "TOWN MAP", "price": 300}],
        "money": 0,
        "bag": [],
    }


def test_task_perception_exposes_both_combatants() -> None:
    memory = Mem(
        {
            W_IS_IN_BATTLE: 1,
            W_BATTLE_MON_LEVEL: 12,
            W_BATTLE_MON_HP: 0x01,
            W_BATTLE_MON_HP + 1: 0x23,
            W_BATTLE_MON_MAX_HP: 0x01,
            W_BATTLE_MON_MAX_HP + 1: 0x40,
            W_BATTLE_MON_STATUS: 0x08,
            W_ENEMY_MON_LEVEL: 3,
            W_ENEMY_MON_HP: 0x00,
            W_ENEMY_MON_HP + 1: 0x09,
            W_ENEMY_MON_MAX_HP: 0x00,
            W_ENEMY_MON_MAX_HP + 1: 0x14,
            W_ENEMY_MON_STATUS: 0x00,
            W_BATTLE_MON_NICK + 7: NAME_END,
            W_ENEMY_MON_NICK + 7: NAME_END,
            **_names(W_BATTLE_MON_NICK, "PIKACHU"),
            **_names(W_ENEMY_MON_NICK, "RATTATA"),
        }
    )

    observation = observe_task(
        _terrain(), ScreenText(in_battle=True), PNG, memory=memory, rom=b"", closed=False
    ).observation

    assert observation.facts.scene is Facts.Scene.BATTLE
    assert observation.facts.battle_status.facts_fields() == observation.facts.model_extra
    assert observation.facts.model_extra == {
        "my_name": "PIKACHU",
        "my_level": "12",
        "my_hp": "291/320",
        "my_status": "PSN",
        "foe_name": "RATTATA",
        "foe_level": "3",
        "foe_hp": "9/20",
        "foe_status": "ok",
    }


def test_new_geometry_and_menu_data_match_the_old_projection_on_the_same_frame() -> None:
    terrain = _terrain()
    text = ScreenText(
        options=["YES", "NO"],
        option_grid=[["YES"], ["NO"]],
        cursor="NO",
        cursor_cell=(1, 0),
        option_details=["×2", ""],
    )

    observation = observe_task(terrain, text, PNG, memory=Mem(), rom=b"", closed=False).observation

    assert observation.facts.cells == terrain.cells
    assert observation.facts.neighbor_cells == terrain.neighbors()
    assert observation.facts.neighbors == terrain.render_neighbors()
    assert observation.facts.walk_map == terrain.render()
    assert observation.facts.option_grid == text.option_grid
    assert observation.facts.cursor_cell == text.cursor_cell
    assert observation.facts.option_annotations == text.option_details
    assert observation.facts.option_layout == text.render_layout()
    assert observation.facts.option_details == text.render_details()
    assert observation.facts.terrain_visible


def test_observation_flags_are_structured_and_leave_the_old_notes_intact() -> None:
    from pokemon_agent.world import TaskObservation

    observation = TaskObservation(
        step=0, status="背包", scene=TaskScene.BAG, menu_decode_complete=False
    )

    restored = TaskObservation.model_validate_json(observation.model_dump_json())

    assert restored.observation_flags == ["no_text", "incomplete_menu", "missing_takeover"]
    assert len(restored.observation_notes) == 3
