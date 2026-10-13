"""存下来的一帧 → `perceive_frame` 要的两样输入：截图字节 + 按绝对地址可读的内存。

帧样本带着整块 WRAM（0xC000–0xDFFF）与截图；通行表在 ROM bank 0
（`ram.read_passable`），所以 WRAM 快照 + ROM 前 16KB 就够 `perceive_frame` 读出与当时
逐字节相同的地形、屏幕文字与战斗状态——不需要起模拟器。
"""

from __future__ import annotations

import base64
import zlib

from evals.common.world_case import ROM
from evals.dataset.frames.schemas import ScreenSample
from pokemon_agent.world.ram import map_settled

WRAM_START, WRAM_END = 0xC000, 0xE000
BANK0_END = 0x4000
PNG_PREFIX = "data:image/png;base64,"


class SnapshotMemory:
    """WRAM 快照 + ROM bank 0 的只读内存（`world.interface.Memory` 的形状）。

    读到这两段以外的地址当场炸：说明 `perceive_frame` 开始读快照里没有的东西
    （切换 bank 的 ROM、VRAM、HRAM），这份快照就不再等价于那一帧了。
    """

    def __init__(self, wram: bytes, bank0: bytes) -> None:
        """前置条件：`wram` 恰好 8KB，`bank0` 至少 16KB。"""
        assert len(wram) == WRAM_END - WRAM_START, f"WRAM 快照应为 8KB，实际 {len(wram)}"
        assert len(bank0) >= BANK0_END, "ROM bank 0 不足 16KB"
        self._wram, self._bank0 = wram, bank0

    def __getitem__(self, address: int | slice) -> int | list[int]:
        """按绝对地址读一个字节或一段。"""
        if isinstance(address, slice):
            return [self._byte(a) for a in range(address.start, address.stop)]
        return self._byte(address)

    def _byte(self, address: int) -> int:
        if WRAM_START <= address < WRAM_END:
            return self._wram[address - WRAM_START]
        assert 0 <= address < BANK0_END, f"快照里没有地址 0x{address:04X}"
        return self._bank0[address]


def has_map(sample: ScreenSample) -> bool:
    """同生产判据：通行表非零且地图头 tileset 与 WRAM 一致才适用地形。"""
    if not sample.wram:
        return False
    wram = zlib.decompress(base64.b64decode(sample.wram))
    return map_settled(SnapshotMemory(wram, bytes(BANK0_END)))


def snapshot_of(sample: ScreenSample) -> tuple[bytes, SnapshotMemory]:
    """样本 → (截图 PNG 字节, 快照内存)。

    前置条件：样本带 WRAM（v2 才有；v1 只有截图与屏幕缓冲，接不进这个节点）。
    """
    assert sample.wram, f"{sample.sample_id} 没有 WRAM 快照（只有 v2 样本能测感知节点）"
    assert sample.frame_png.startswith(PNG_PREFIX), "截图应为 PNG data URI"
    png = base64.b64decode(sample.frame_png.removeprefix(PNG_PREFIX))
    wram = zlib.decompress(base64.b64decode(sample.wram))
    return png, SnapshotMemory(wram, ROM.read_bytes()[:BANK0_END])


__all__ = ["SnapshotMemory", "has_map", "snapshot_of"]
