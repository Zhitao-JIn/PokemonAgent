"""地图头 tileset 静态表；运行时不读取 ROM，缺表或损坏直接报错。"""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def map_tilesets() -> tuple[int, ...]:
    """返回不可变地图头表；调用方使用地图编号索引。"""
    raw = json.loads(
        (Path(__file__).parent / "tables" / "map_tilesets.json").read_text(encoding="utf-8")
    )
    return tuple(raw[str(index)] for index in range(len(raw)))
