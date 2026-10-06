"""脚本使用的地图与商店静态表。"""

from pathlib import Path
from typing import Any

_TABLES = Path(__file__).resolve().parent.parent / "tables"


def _load_table(name: str) -> dict[str, Any]:
    """读取 `world/tables/<name>`（表是数据，缺文件不报错——P4 脚本按需取）。"""
    path = _TABLES / name
    if not path.exists():
        return {}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


WARPS = _load_table("warps.json")
SHOP_LAYOUTS = _load_table("shop_layouts.json")
POKECENTER_LAYOUTS = _load_table("pokecenter_layouts.json")
