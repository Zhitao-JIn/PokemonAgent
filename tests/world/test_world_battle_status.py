"""战斗双方状态框：不在战斗返回 None，名字按终止符截止，HP 两字节高位在前。"""

from __future__ import annotations

import pytest

from pokemon_agent.world.battle_status import read_battle_status, status_abbr
from pokemon_agent.world.ram import (
    NAME_END,
    W_BATTLE_MON_HP,
    W_BATTLE_MON_LEVEL,
    W_BATTLE_MON_MAX_HP,
    W_BATTLE_MON_NICK,
    W_BATTLE_MON_STATUS,
    W_ENEMY_MON_HP,
    W_ENEMY_MON_LEVEL,
    W_ENEMY_MON_MAX_HP,
    W_ENEMY_MON_NICK,
    W_ENEMY_MON_STATUS,
)
from pokemon_agent.world.screen_text import CHARMAP, W_IS_IN_BATTLE

_TILE = {text: tile for tile, text in CHARMAP.items()}


class Mem:
    """按地址取字节的假内存：未写的地址读 0。"""

    def __init__(self, values: dict[int, int]) -> None:
        self._values = dict(values)

    def __getitem__(self, address: int) -> int:
        return self._values.get(address, 0)


def _name(address: int, text: str) -> dict[int, int]:
    """名字缓冲：一个字符一个字节。"""
    return {address + offset: _TILE[character] for offset, character in enumerate(text)}


def test_outside_battle_returns_none() -> None:
    assert read_battle_status(Mem({W_IS_IN_BATTLE: 0})) is None


def test_reads_both_sides_names_levels_and_big_endian_hp() -> None:
    mem = Mem(
        {
            W_IS_IN_BATTLE: 1,
            W_BATTLE_MON_LEVEL: 12,
            W_BATTLE_MON_HP: 0x01,
            W_BATTLE_MON_HP + 1: 0x23,
            W_BATTLE_MON_MAX_HP: 0x01,
            W_BATTLE_MON_MAX_HP + 1: 0x40,
            W_BATTLE_MON_STATUS: 0x08,
            W_ENEMY_MON_LEVEL: 3,
            W_ENEMY_MON_HP: 0x00,
            W_ENEMY_MON_HP + 1: 0x09,
            W_ENEMY_MON_MAX_HP: 0x00,
            W_ENEMY_MON_MAX_HP + 1: 0x14,
            W_ENEMY_MON_STATUS: 0x00,
            **_name(W_BATTLE_MON_NICK, "PIKACHU"),
            **_name(W_ENEMY_MON_NICK, "RATTATA"),
        }
    )

    status = read_battle_status(mem)

    assert status is not None
    assert (status.mine.name, status.mine.level) == ("PIKACHU", 12)
    assert (status.mine.hp, status.mine.max_hp) == (291, 320)
    assert status.mine.status == "PSN"
    assert (status.foe.name, status.foe.level) == ("RATTATA", 3)
    assert (status.foe.hp, status.foe.max_hp) == (9, 20)
    assert status.foe.status == "ok"


def test_name_stops_at_terminator() -> None:
    mem = Mem(
        {
            W_IS_IN_BATTLE: 1,
            **_name(W_BATTLE_MON_NICK, "PIKACHU"),
            W_BATTLE_MON_NICK + 3: NAME_END,
        }
    )

    status = read_battle_status(mem)

    assert status is not None
    assert status.mine.name == "PIK"


@pytest.mark.parametrize(
    ("byte", "abbr"),
    [(0x00, "ok"), (0x40, "PAR"), (0x20, "FRZ"), (0x10, "BRN"), (0x08, "PSN"), (0x07, "SLP")],
)
def test_status_abbr_maps_each_status_bit(byte: int, abbr: str) -> None:
    assert status_abbr(byte) == abbr
