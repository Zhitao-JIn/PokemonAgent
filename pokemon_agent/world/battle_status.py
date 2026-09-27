"""读战斗双方状态框：名字、等级、HP、最大 HP、状态异常——全部是游戏变量，不经视觉模型。

地址在 `ram.py`；名字按 `screen_text.CHARMAP`（《红》英文字表）解码。不在战斗时返回 None。
"""

from __future__ import annotations

from .interface import BattleStatus, Combatant, Memory
from .ram import (
    NAME_END,
    NAME_LENGTH,
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
from .screen_text import CHARMAP, W_IS_IN_BATTLE

_STATUS_BITS: tuple[tuple[int, str], ...] = (
    (0x40, "PAR"),
    (0x20, "FRZ"),
    (0x10, "BRN"),
    (0x08, "PSN"),
    (0x07, "SLP"),
)


def read_battle_status(mem: Memory) -> BattleStatus | None:
    """战斗中返回双方状态框；`wIsInBattle` 为 0 时返回 None。"""
    if mem[W_IS_IN_BATTLE] == 0:
        return None
    mine = _combatant(
        mem,
        W_BATTLE_MON_NICK,
        W_BATTLE_MON_LEVEL,
        W_BATTLE_MON_HP,
        W_BATTLE_MON_MAX_HP,
        W_BATTLE_MON_STATUS,
    )
    foe = _combatant(
        mem,
        W_ENEMY_MON_NICK,
        W_ENEMY_MON_LEVEL,
        W_ENEMY_MON_HP,
        W_ENEMY_MON_MAX_HP,
        W_ENEMY_MON_STATUS,
    )
    return BattleStatus(mine=mine, foe=foe)


def _combatant(mem: Memory, nick: int, level: int, hp: int, max_hp: int, status: int) -> Combatant:
    """一方状态框的五个量。"""
    return Combatant(
        name=_name(mem, nick),
        level=mem[level],
        hp=u16(mem, hp),
        max_hp=u16(mem, max_hp),
        status=status_abbr(mem[status]),
    )


def u16(mem: Memory, addr: int) -> int:
    """两字节、高位在前。"""
    return mem[addr] * 256 + mem[addr + 1]


def _name(mem: Memory, addr: int) -> str:
    """定长名字缓冲 → 字符串，遇 `NAME_END` 截止；不在字表里的字节跳过。"""
    chars: list[str] = []
    for i in range(NAME_LENGTH):
        byte = mem[addr + i]
        if byte == NAME_END:
            break
        chars.append(CHARMAP.get(byte, ""))
    return "".join(chars)


def status_abbr(byte: int) -> str:
    """状态字节 → 画面上的缩写；没有异常为 `ok`。"""
    return next((abbr for mask, abbr in _STATUS_BITS if byte & mask), "ok")


__all__ = ["read_battle_status", "status_abbr", "u16"]
