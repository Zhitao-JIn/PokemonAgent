"""三张静态表：地图键与溯源、门的落点、服务图站位、图块集对应。"""

from __future__ import annotations

import pytest

from pokemon_agent.world.map_tilesets import map_tilesets
from pokemon_agent.world.scripts.tables import (
    POKECENTER_LAYOUTS,
    SHOP_LAYOUTS,
    WARPS,
)

TABLES = {"warps": WARPS, "shop": SHOP_LAYOUTS, "center": POKECENTER_LAYOUTS}
MAP_KEYS = {
    "warps": {"12", "40", "41", "42"},
    "shop": {"42", "56", "67"},
    "center": {"41", "58", "64"},
}


def _map_keys(table: dict[str, object]) -> set[str]:
    """业务地图键：排除 `_source` / `_note` 这类下划线开头的溯源字段。"""
    return {key for key in table if not key.startswith("_")}


@pytest.mark.parametrize(("name", "expected"), MAP_KEYS.items(), ids=MAP_KEYS.keys())
def test_world_tables_keep_map_keys_and_provenance(name: str, expected: set[str]) -> None:
    table = TABLES[name]

    assert _map_keys(table) == expected
    assert isinstance(table["_source"], str) and table["_source"]
    assert isinstance(table["_note"], str) and table["_note"]
    if name == "warps":
        assert table["_coords"]
        assert isinstance(table["_indoor_source"], str) and table["_indoor_source"]


def test_known_warps_keep_door_and_edge_destinations() -> None:
    for key in ("41", "42"):
        assert WARPS[key]["door_warps"] == [{"x": 3, "y": 7, "dir": "down", "to_map": 1}]
        assert WARPS[key]["edge_exits"] == []
    assert WARPS["40"]["door_warps"] == [{"x": 4, "y": 11, "dir": "down", "to_map": 0}]
    assert WARPS["40"]["edge_exits"] == []

    assert WARPS["12"]["size"] == {"w": 10, "h": 18}
    assert WARPS["12"]["door_warps"] == []
    edges = {edge["edge"]: edge for edge in WARPS["12"]["edge_exits"]}
    assert set(edges) == {"north", "south"}
    assert (edges["north"]["dir"], edges["north"]["to_map"], edges["north"]["conn_offset"]) == (
        "up",
        1,
        -5,
    )
    assert (edges["south"]["dir"], edges["south"]["to_map"], edges["south"]["conn_offset"]) == (
        "down",
        0,
        0,
    )
    assert edges["north"]["trigger"] == edges["south"]["trigger"] == "step_off_edge"


@pytest.mark.parametrize(
    ("table", "map_key"),
    [
        (SHOP_LAYOUTS, "42"),
        (SHOP_LAYOUTS, "56"),
        (SHOP_LAYOUTS, "67"),
        (POKECENTER_LAYOUTS, "41"),
        (POKECENTER_LAYOUTS, "58"),
        (POKECENTER_LAYOUTS, "64"),
    ],
    ids=["shop-42", "shop-56", "shop-67", "center-41", "center-58", "center-64"],
)
def test_service_layouts_keep_counter_standing_positions(
    table: dict[str, object], map_key: str
) -> None:
    entry = table[map_key]

    if table is SHOP_LAYOUTS:
        assert entry["clerk"] == {"x": 0, "y": 5, "facing": "right"}
        assert entry["stand"] == {"x": 2, "y": 5, "facing": "west"}
        goods = entry["goods"]
        assert isinstance(goods, list) and goods
        assert all(isinstance(good["item"], str) and good["item"] for good in goods)
        assert all(isinstance(good["price"], int) for good in goods)
    else:
        assert entry["nurse"] == {"x": 3, "y": 1, "facing": "down"}
        assert entry["stand"] == {"x": 3, "y": 3, "facing": "north"}


def test_service_map_tilesets_match_their_layouts() -> None:
    tilesets = map_tilesets()

    for map_key in ("42", "56", "67"):
        assert tilesets[int(map_key)] == 2
    for map_key in ("41", "58", "64"):
        assert tilesets[int(map_key)] == 6
