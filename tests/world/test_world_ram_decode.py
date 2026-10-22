"""ram 解码：精灵朝向字节、可通行 tile 表读到 `0xFF` 为止。"""

from __future__ import annotations

import pytest

from pokemon_agent.world.ram import (
    W_COLLISION_PTR,
    W_SPRITES,
    read_facing,
    read_passable,
)

COLLISION_LIST = 0xC000
"""通行表假件的落点；指针两个字节指向它。"""


class Mem:
    """按地址取字节的假内存：未写的地址读 0。"""

    def __init__(self, values: dict[int, int]) -> None:
        self._values = dict(values)

    def __getitem__(self, address: int) -> int:
        return self._values.get(address, 0)


def _pointing_at(address: int) -> dict[int, int]:
    """通行表指针：低字节在前。"""
    return {W_COLLISION_PTR: address & 0xFF, W_COLLISION_PTR + 1: address >> 8}


@pytest.mark.parametrize(
    ("byte", "expected"),
    [(0, "south"), (4, "north"), (8, "west"), (12, "east")],
)
def test_facing_from_sprite_byte(byte: int, expected: str) -> None:
    mem = Mem({W_SPRITES + 9: byte})

    assert read_facing(mem) == expected


def test_passable_reads_list_until_ff() -> None:
    values = _pointing_at(COLLISION_LIST)
    for offset, byte in enumerate((0x01, 0x05, 0x2C, 0xFF)):
        values[COLLISION_LIST + offset] = byte

    assert read_passable(Mem(values)) == {1, 5, 44}


def test_passable_empty_list_asserts() -> None:
    values = _pointing_at(COLLISION_LIST)
    values[COLLISION_LIST] = 0xFF

    with pytest.raises(AssertionError):
        read_passable(Mem(values))
