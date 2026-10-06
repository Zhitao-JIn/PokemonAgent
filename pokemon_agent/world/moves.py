"""招式的名字。

名字表来自 `pret/pokered` 反汇编（`tables/moves.json`）。纯函数，给战斗接管脚本与视图用。
"""

from __future__ import annotations

import json
from pathlib import Path

_NAMES: dict[int, str] = {
    int(k): v
    for k, v in json.loads(
        (Path(__file__).parent / "tables" / "moves.json").read_text("utf-8")
    ).items()
}


def move_name(move_id: int) -> str:
    """招式 id → 名字；表里没有的写成 `MOVE_0x..`。"""
    return _NAMES.get(move_id, f"MOVE_0x{move_id:02X}")


def fold(name: str) -> str:
    """比对名字用的规范形：大写、`é` 当 `e`、空白归一。"""
    return " ".join(name.replace("é", "e").replace("É", "E").upper().split())


__all__ = ["fold", "move_name"]
