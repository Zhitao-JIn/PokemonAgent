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
from pokemon_agent.world import Facts, TaskScene


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
    """最终当前帧仍显示 BUY / SELL / QUIT 三项选单。"""
    frames = target_frames(stream, sample)
    if not frames:
        return unjudgeable("没有目标帧")
    current = frames[-1]
    ram = current.content.ram
    if ram is None or ram.text_source != "decode":
        return unjudgeable("最终当前帧没有解码来源")
    if current.content.facts.overlay == Facts.Overlay.CHOICE and current.text.options == [
        "BUY",
        "SELL",
        "QUIT",
    ]:
        return passed("最终当前帧仍显示 BUY / SELL / QUIT", current)
    return failed("最终当前帧未显示 BUY / SELL / QUIT 选单", current)


@rule("shop_all_npcs_interacted")
def shop_all_npcs_interacted(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """本 task 起点可见的每个 NPC 都至少产生过一次对话交互事件。"""
    episodes = stream.episodes_for(sample.sample_id)
    frames = stream.frames(episodes)
    if not frames:
        return unjudgeable("没有目标局的观测帧")
    people = {
        (mark.map_id, mark.x, mark.y)
        for mark in frames[0].content.facts.landmarks
        if mark.kind == "人"
    }
    if not people:
        return unjudgeable("起点观测没有可核对的 NPC 地标")
    interacted: dict[tuple[int, int, int], str] = {}
    for event in stream.in_episodes(episodes, "write_object_memory"):
        content = event.content.model_dump(mode="python")
        place = content.get("place")
        if content.get("object_kind") != "人" or content.get("outcome") != "dialog":
            continue
        if not isinstance(place, dict):
            continue
        key = (place.get("map_id"), place.get("x"), place.get("y"))
        if key in people:
            interacted[key] = event.uuid
    missing = people - set(interacted)
    if missing:
        return failed(f"还有 {len(missing)} 位起点 NPC 没有对话交互记录")
    return CheckVerdict(
        outcome="pass",
        evidence=[interacted[key] for key in sorted(people)],
        reason=f"本 task 已与起点可见的 {len(people)} 位 NPC 各交互至少一次",
    )


@rule("shop_two_npcs_interacted")
def shop_two_npcs_interacted(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """本 task 起点可见的至少两位不同 NPC 各有一次对话交互事件。"""
    episodes = stream.episodes_for(sample.sample_id)
    frames = stream.frames(episodes)
    if not frames:
        return unjudgeable("没有目标局的观测帧")
    people = {
        (mark.map_id, mark.x, mark.y)
        for mark in frames[0].content.facts.landmarks
        if mark.kind == "人"
    }
    if len(people) < 2:
        return unjudgeable("起点观测不足两位可核对的 NPC 地标")
    interacted: dict[tuple[int, int, int], str] = {}
    for event in stream.in_episodes(episodes, "write_object_memory"):
        content = event.content.model_dump(mode="python")
        place = content.get("place")
        if content.get("object_kind") != "人" or content.get("outcome") != "dialog":
            continue
        if not isinstance(place, dict):
            continue
        key = (place.get("map_id"), place.get("x"), place.get("y"))
        if key in people:
            interacted[key] = event.uuid
    if len(interacted) < 2:
        return failed(f"只与 {len(interacted)} 位不同 NPC 完成对话，至少需要 2 位")
    evidence = [interacted[key] for key in sorted(interacted)[:2]]
    return CheckVerdict(
        outcome="pass",
        evidence=evidence,
        reason=f"本 task 已与起点可见的 {len(interacted)} 位不同 NPC 完成对话（要求至少 2 位）",
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
    """本 task 历史中 `buy_item` 脚本以 `ok` 正常结束即买成。"""
    episodes = stream.episodes_for(sample.sample_id)
    if not episodes:
        return unjudgeable("没有目标局")
    calls = stream.in_episodes(episodes, "act_call")
    script_calls = [
        event for event in calls if getattr(event.content, "script", None) == "buy_item"
    ]
    for event in script_calls:
        if event.content.ok == "true" and event.content.code == "ok":
            return CheckVerdict(
                outcome="pass",
                evidence=[event.uuid],
                reason="本 task 历史记录 buy_item → ok",
            )
    if script_calls:
        last = script_calls[-1].content
        return failed(f"本 task 历史 buy_item 未正常结束：{last.code or '无结局码'}")
    return failed("本 task 历史中没有 buy_item 脚本调用")


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
    "shop_all_npcs_interacted",
    "shop_two_npcs_interacted",
    "shop_bought",
    "shop_cancelled",
    "shop_item_selected",
    "shop_list_opened",
    "shop_menu_opened",
]
