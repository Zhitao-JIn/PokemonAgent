"""地形精灵层的可见槽位与地图坐标；只读同帧 WRAM。"""

from .interface import Memory

W_MISSABLE_FLAGS = 0xD5A6
W_MISSABLE_LIST = 0xD5CE
W_SPRITE_MAP_Y = 0xC204
W_SPRITE_MAP_X = 0xC205
SPRITE_STRIDE = 16


def hidden_slots(memory: Memory) -> set[int]:
    """隐藏位为一的槽位不进地形；前置条件：内存可读 missable 表与位图。"""
    hidden: set[int] = set()
    for offset in range(0, 32, 2):
        slot = int(memory[W_MISSABLE_LIST + offset])
        if slot == 0xFF:
            break
        index = int(memory[W_MISSABLE_LIST + offset + 1])
        if int(memory[W_MISSABLE_FLAGS + index // 8]) >> (index % 8) & 1:
            hidden.add(slot)
    return hidden


def sprite_position(memory: Memory, slot: int) -> tuple[int, int]:
    """返回地图 x/y；移动中的精灵按游戏已更新的目标格定位。"""
    assert 1 <= slot < 16
    return (
        int(memory[W_SPRITE_MAP_X + SPRITE_STRIDE * slot]) - 4,
        int(memory[W_SPRITE_MAP_Y + SPRITE_STRIDE * slot]) - 4,
    )
