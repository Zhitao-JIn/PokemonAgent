"""地图头 tileset 表：按下标索引，且与 JSON 表逐项一致；整表缓存为同一对象。"""

from __future__ import annotations

import json
from pathlib import Path

from pokemon_agent.world import map_tilesets as module
from pokemon_agent.world.map_tilesets import map_tilesets

TABLE = json.loads(
    (Path(module.__file__).parent / "tables" / "map_tilesets.json").read_text(encoding="utf-8")
)


def test_tilesets_indexed_by_map_id() -> None:
    table = map_tilesets()

    assert isinstance(table, tuple)
    assert len(table) == 248
    assert list(table) == [TABLE[str(index)] for index in range(len(TABLE))]


def test_tilesets_cached_single_object() -> None:
    assert map_tilesets() is map_tilesets()
