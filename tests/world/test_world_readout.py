"""内存读数：三字节 BCD 金钱、背包与队伍的数量封顶与 `LIST_END` 截止。"""

from __future__ import annotations

import pytest

from pokemon_agent.world.interface import BagItem, PartyMon
from pokemon_agent.world.ram import (
    BAG_CAPACITY,
    LIST_END,
    PARTY_MON_SIZE,
    W_BAG_ITEMS,
    W_NUM_BAG_ITEMS,
    W_PARTY_COUNT,
    W_PARTY_MON1_HP,
    W_PARTY_SPECIES,
    W_PLAYER_MONEY,
)
from pokemon_agent.world.readout import read_bag, read_money, read_party

LEVEL_OFFSET = 0x20
"""队伍条目里等级的偏移（`read_party` 按 `base + 0x20` 读）。"""

MAX_HP_OFFSET = 0x21
STATUS_OFFSET = 3


class Mem:
    """按地址取字节的假内存：未写的地址读 0。"""

    def __init__(self, values: dict[int, int]) -> None:
        self._values = dict(values)

    def __getitem__(self, address: int) -> int:
        return self._values.get(address, 0)


def _mon(index: int, species: int, level: int, hp: int, max_hp: int, status: int) -> dict[int, int]:
    """一只队伍成员占的字节：`PARTY_MON_SIZE` 一格。"""
    base = W_PARTY_MON1_HP + index * PARTY_MON_SIZE
    return {
        W_PARTY_SPECIES + index: species,
        base: hp >> 8,
        base + 1: hp & 0xFF,
        base + STATUS_OFFSET: status,
        base + LEVEL_OFFSET: level,
        base + MAX_HP_OFFSET: max_hp >> 8,
        base + MAX_HP_OFFSET + 1: max_hp & 0xFF,
    }


@pytest.mark.parametrize(
    ("bcd", "expected"),
    [
        ((0x12, 0x34, 0x56), 123456),
        ((0x00, 0x30, 0x00), 3000),
        ((0x00, 0x03, 0x00), 300),
    ],
)
def test_money_is_three_byte_bcd(bcd: tuple[int, int, int], expected: int) -> None:
    mem = Mem({W_PLAYER_MONEY + offset: byte for offset, byte in enumerate(bcd)})

    assert read_money(mem) == expected


def test_bag_stops_at_list_end() -> None:
    mem = Mem(
        {
            W_NUM_BAG_ITEMS: 3,
            W_BAG_ITEMS + 0: 4,
            W_BAG_ITEMS + 1: 5,
            W_BAG_ITEMS + 2: 10,
            W_BAG_ITEMS + 3: 2,
            W_BAG_ITEMS + 4: LIST_END,
        }
    )

    assert read_bag(mem) == [
        BagItem(item_id=4, quantity=5),
        BagItem(item_id=10, quantity=2),
    ]


def test_bag_capped_at_capacity() -> None:
    values = {W_NUM_BAG_ITEMS: 25}
    for index in range(BAG_CAPACITY):
        values[W_BAG_ITEMS + 2 * index] = index + 1
        values[W_BAG_ITEMS + 2 * index + 1] = 1

    bag = read_bag(Mem(values))

    assert len(bag) == BAG_CAPACITY
    assert bag[-1].item_id == BAG_CAPACITY


def test_party_reads_fields_for_count_only() -> None:
    values = {W_PARTY_COUNT: 2}
    values.update(_mon(0, species=153, level=12, hp=291, max_hp=320, status=0x08))
    values.update(_mon(1, species=37, level=3, hp=9, max_hp=20, status=0x00))

    assert read_party(Mem(values)) == [
        PartyMon(species=153, level=12, hp=291, max_hp=320, status="PSN"),
        PartyMon(species=37, level=3, hp=9, max_hp=20, status="ok"),
    ]


def test_party_capped_at_six() -> None:
    mem = Mem({W_PARTY_COUNT: 9})

    assert len(read_party(mem)) == 6
