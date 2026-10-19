"""地形精灵：missable 位图决定隐藏槽位，地图坐标相对屏幕原点偏移 4。"""

from __future__ import annotations

import pytest

from pokemon_agent.world.terrain_sprites import (
    SPRITE_STRIDE,
    W_MISSABLE_FLAGS,
    W_MISSABLE_LIST,
    W_SPRITE_MAP_X,
    W_SPRITE_MAP_Y,
    hidden_slots,
    sprite_position,
)

LIST_END = 0xFF
"""missable 表的终止字节。"""


class Mem:
    """按地址取字节的假内存：未写的地址读 0。"""

    def __init__(self, values: dict[int, int]) -> None:
        self._values = dict(values)

    def __getitem__(self, address: int) -> int:
        return self._values.get(address, 0)


def test_hidden_slots_flagged_only() -> None:
    mem = Mem(
        {
            W_MISSABLE_LIST + 0: 3,
            W_MISSABLE_LIST + 1: 7,
            W_MISSABLE_LIST + 2: 5,
            W_MISSABLE_LIST + 3: 2,
            W_MISSABLE_LIST + 4: LIST_END,
            W_MISSABLE_FLAGS + 0: 0x80,
        }
    )

    assert hidden_slots(mem) == {3}


def test_sprite_position_offset_minus_four() -> None:
    mem = Mem(
        {
            W_SPRITE_MAP_X + SPRITE_STRIDE * 2: 10,
            W_SPRITE_MAP_Y + SPRITE_STRIDE * 2: 7,
        }
    )

    assert sprite_position(mem, 2) == (6, 3)


@pytest.mark.parametrize("slot", [0, 16])
def test_sprite_slot_range_asserts(slot: int) -> None:
    with pytest.raises(AssertionError):
        sprite_position(Mem({}), slot)
