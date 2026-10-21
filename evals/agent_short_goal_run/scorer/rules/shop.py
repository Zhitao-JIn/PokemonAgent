"""商店类判据：买没买成看金钱与背包（游戏变量）；界面走到哪一步看解码出的选项与附注。"""

from __future__ import annotations

import re

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
    decoded,
    ends,
    failed,
    first_match,
    passed,
    target_frames,
    unjudgeable,
)
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict
from pokemon_agent.world import TaskScene


def _quantity_selected(frame: Frame) -> bool:
    """商店整屏 RAM 解码中有数量与总价的独立框；它不进入底部 dialog_text。"""
    ram = frame.content.ram
    if ram is None or ram.text_source != "decode" or frame.content.scene != TaskScene.SHOP_ITEMS:
        return False
    lines = frame.content.facts.screen.splitlines()
    return any(
        re.search(r"│×\d{2}\s+¥\d+\s*│", lines[index])
        and re.search(r"┌─+┐", lines[index - 1])
        and re.search(r"└─+┘", lines[index + 1])
        for index in range(1, len(lines) - 1)
    )


def _has_prices(frame: Frame) -> bool:
    """这一帧是带价格的商品列表。"""
    details = (frame.content.facts.model_extra or {}).get("option_details", "")
    return "¥" in str(details)


def _bag(frame: Frame) -> dict[int, int]:
    """背包：物品 ID → 数量。"""
    assert frame.content.ram is not None
    return {item.item_id: item.quantity for item in frame.content.ram.bag}


@rule("shop_menu_opened")
def shop_menu_opened(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """出现过 BUY / SELL / QUIT 三项选单。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")
    return first_match(
        frames,
        lambda f: f.text.options == ["BUY", "SELL", "QUIT"],
        found="出现了 BUY / SELL / QUIT",
        missing="从没出现 BUY / SELL / QUIT",
    )


@rule("shop_list_opened")
def shop_list_opened(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """出现过带价格的商品列表。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")
    return first_match(frames, _has_prices, found="出现了商品列表", missing="从没出现商品列表")


@rule("shop_item_selected")
def shop_item_selected(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """进了购买确认：出现 YES / NO，或店员问数量 / 报价。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧")
    return first_match(
        frames,
        lambda f: (
            _quantity_selected(f)
            or f.text.options == ["YES", "NO"]
            or any(s in f.text.dialog_text for s in ("How many", "That will be"))
        ),
        found="进了购买确认",
        missing="没进购买确认",
    )


@rule("shop_bought")
def shop_bought(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """买成了：金钱少了，且背包里有一种物品多了。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    if pair is None:
        return unjudgeable("目标局里不足两帧带内存读数")
    start = pair[0]
    assert start.content.ram is not None
    before = _bag(start)
    for frame in frames:
        ram = frame.content.ram
        if ram is None or ram.money >= start.content.ram.money:
            continue
        if any(qty > before.get(item, 0) for item, qty in _bag(frame).items()):
            return passed(
                f"金钱 {start.content.ram.money} → {ram.money}，背包多了一件", start, frame
            )
    return failed("金钱与背包都没变成买到的样子", start, pair[1])


@rule("shop_cancelled")
def shop_cancelled(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """退回商品列表且没花钱：最后一帧解码帧是带价格的列表，金钱与开局相同。"""
    frames = target_frames(stream, sample)
    pair = ends(frames)
    texts = decoded(frames)
    if pair is None or not texts:
        return unjudgeable("帧不够或没有解码来源的帧")
    start, last = pair
    assert start.content.ram is not None and last.content.ram is not None
    shown = texts[-1]
    if last.content.ram.money != start.content.ram.money:
        return failed("金钱变了，买下去了", start, last)
    if _has_prices(shown) and shown.text.options != ["YES", "NO"]:
        return passed("退回了商品列表，没花钱", start, shown)
    return failed("最后一帧解码帧不是商品列表", shown)


__all__ = [
    "shop_bought",
    "shop_cancelled",
    "shop_item_selected",
    "shop_list_opened",
    "shop_menu_opened",
]
