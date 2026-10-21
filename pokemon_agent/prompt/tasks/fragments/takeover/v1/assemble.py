"""注册片段 v1：固定文本与原料排版。"""

from __future__ import annotations

import json
from pathlib import Path

from ....interfaces.assembly import Compose
from ....observation import (
    BagView,
    BattleMenuView,
    BattleSwitchView,
    LearnMoveView,
    MonEntry,
    NamingView,
    PartyView,
    PcView,
    ShopItemsView,
)
from .params import TakeoverParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def shopitems_render(self: ShopItemsView) -> str:
    """按原条件和顺序渲染独立原料。"""
    goods = (
        _LABELS["L000"].join(_LABELS["L001"].format(i.name, i.price) for i in self.items)
        or _LABELS["L002"]
    )
    bag = (
        _LABELS["L003"].join(_LABELS["L004"].format(b.name, b.quantity) for b in self.bag)
        or _LABELS["L005"]
    )
    return _LABELS["L006"].format(goods, self.money, bag)


def naming_render(self: NamingView) -> str:
    """按原条件和顺序渲染独立原料。"""
    return _LABELS["L008"].format(self.target, self.typed or _LABELS["L007"])


def mon_render(self: MonEntry) -> str:
    """按原条件和顺序渲染独立原料。"""
    tags = [t for t in (self.status if self.status != "ok" else "",) if t]
    if self.active:
        tags.append(_LABELS["L009"])
    if self.hp == 0 and self.max_hp:
        tags.append(_LABELS["L010"])
    suffix = _LABELS["L012"].format(_LABELS["L011"].join(tags)) if tags else ""
    return _LABELS["L013"].format(self.name, self.level, self.hp, self.max_hp, suffix)


def battlemenu_render(self: BattleMenuView) -> str:
    """按原条件和顺序渲染独立原料。"""
    moves = (
        _LABELS["L014"].join(_LABELS["L015"].format(m.name, m.pp) for m in self.mine.moves)
        or _LABELS["L016"]
    )
    party = _LABELS["L017"].join(mon_render(m) for m in self.party) or _LABELS["L018"]
    bag = (
        _LABELS["L019"].join(_LABELS["L020"].format(b.name, b.quantity) for b in self.bag)
        or _LABELS["L021"]
    )
    kind = _LABELS["L022"] if self.trainer else _LABELS["L023"]
    return _LABELS["L024"].format(
        kind, mon_render(self.mine), moves, mon_render(self.foe), party, bag
    )


def battleswitch_render(self: BattleSwitchView) -> str:
    """按原条件和顺序渲染独立原料。"""
    return _LABELS["L025"] + (
        _LABELS["L026"].join(mon_render(m) for m in self.party) or _LABELS["L027"]
    )


def bag_render(self: BagView) -> str:
    """按原条件和顺序渲染独立原料。"""
    bag = (
        _LABELS["L028"].join(_LABELS["L029"].format(b.name, b.quantity) for b in self.bag)
        or _LABELS["L030"]
    )
    party = _LABELS["L031"].join(mon_render(m) for m in self.party) or _LABELS["L032"]
    return _LABELS["L033"].format(bag, party)


def party_render(self: PartyView) -> str:
    """按原条件和顺序渲染独立原料。"""
    lines = [
        _LABELS["L034"].format(i + 1, mon_render(m))
        + (_LABELS["L035"].join(x.name for x in m.moves) or _LABELS["L036"])
        for i, m in enumerate(self.party)
    ]
    return _LABELS["L037"] + ("\n".join(lines) or _LABELS["L038"])


def pc_render(self: PcView) -> str:
    """按原条件和顺序渲染独立原料。"""
    items = (
        _LABELS["L039"].join(_LABELS["L040"].format(b.name, b.quantity) for b in self.items)
        or _LABELS["L041"]
    )
    bag = (
        _LABELS["L042"].join(_LABELS["L043"].format(b.name, b.quantity) for b in self.bag)
        or _LABELS["L044"]
    )
    box = (
        _LABELS["L045"].join(_LABELS["L046"].format(m.name, m.level) for m in self.box)
        or _LABELS["L047"]
    )
    party = _LABELS["L048"].join(mon_render(m) for m in self.party) or _LABELS["L049"]
    return _LABELS["L050"].format(items, bag, self.box_number, box, party)


def learnmove_render(self: LearnMoveView) -> str:
    """按原条件和顺序渲染独立原料。"""
    known = (
        _LABELS["L051"].join(_LABELS["L052"].format(m.name, m.pp) for m in self.moves)
        or _LABELS["L053"]
    )
    return _LABELS["L054"].format(self.pokemon, self.new_move, known)


def assemble(params: TakeoverParams, compose: Compose) -> str:
    """按判别联合分派，不猜测视图内容。"""
    if isinstance(params.view, ShopItemsView):
        return shopitems_render(params.view)
    if isinstance(params.view, NamingView):
        return naming_render(params.view)
    if isinstance(params.view, BattleMenuView):
        return battlemenu_render(params.view)
    if isinstance(params.view, BattleSwitchView):
        return battleswitch_render(params.view)
    if isinstance(params.view, BagView):
        return bag_render(params.view)
    if isinstance(params.view, PartyView):
        return party_render(params.view)
    if isinstance(params.view, PcView):
        return pc_render(params.view)
    if isinstance(params.view, LearnMoveView):
        return learnmove_render(params.view)
    raise AssertionError("Unknown takeover view")
