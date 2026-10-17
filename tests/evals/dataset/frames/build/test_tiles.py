"""tiles_from_wram：8192 字节 WRAM → 18×20 地图块矩阵的映射。"""

from __future__ import annotations

import pytest

from evals.dataset.frames.build.tiles import tiles_from_wram
from pokemon_agent.world import W_TILEMAP


def test_tiles_from_wram_maps_four_corners_and_a_middle_point() -> None:
    """合成字节核对 18×20 映射的四角与一个中间点。"""
    wram = bytearray(8192)
    base = W_TILEMAP - 0xC000
    wram[base + 0 * 20 + 0] = 1
    wram[base + 0 * 20 + 19] = 2
    wram[base + 17 * 20 + 0] = 3
    wram[base + 17 * 20 + 19] = 4
    wram[base + 9 * 20 + 10] = 5

    tiles = tiles_from_wram(bytes(wram))

    assert len(tiles) == 18 and all(len(row) == 20 for row in tiles)
    assert tiles[0][0] == 1
    assert tiles[0][19] == 2
    assert tiles[17][0] == 3
    assert tiles[17][19] == 4
    assert tiles[9][10] == 5


def test_tiles_from_wram_rejects_wrong_length() -> None:
    """长度不是 8192 → 断言失败。"""
    with pytest.raises(AssertionError, match="8192"):
        tiles_from_wram(b"\x00" * 100)
