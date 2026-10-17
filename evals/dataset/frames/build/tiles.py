"""从 8192 字节 WRAM 快照派生 18×20 地图块矩阵（数据集冻结用）。"""

from __future__ import annotations

from pokemon_agent.world import W_TILEMAP


def tiles_from_wram(wram: bytes) -> list[list[int]]:
    """把 WRAM 快照（0xC000–0xDFFF）的图块缓冲区展开成 18 行 × 20 列。

    前置条件：`wram` 恰为 8192 字节，否则断言失败。
    """
    assert len(wram) == 8192, "WRAM 快照应为 8192 字节"
    base = W_TILEMAP - 0xC000
    return [[wram[base + row * 20 + col] for col in range(20)] for row in range(18)]


__all__ = ["tiles_from_wram"]
