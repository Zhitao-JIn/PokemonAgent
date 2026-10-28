"""五条中期 run 粒度判据。"""

from __future__ import annotations

import re

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import rule
from evals.agent_short_goal_run.scorer.stream import Frame, RunStream
from evals.agent_short_goal_run.scorer.utils import (
    ends,
    failed,
    passed,
    target_frames,
    unjudgeable,
    with_ram,
)
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict
from pokemon_agent.world.items import item_id

from .catch import _foe_hp, ball_caught
from .center import _all_healed

_POKE_BALL = item_id("POKé BALL")
_ANTIDOTE = item_id("ANTIDOTE")
_PARLYZ_HEAL = item_id("PARLYZ HEAL")
_BURN_HEAL = item_id("BURN HEAL")
_DIALOG_A = re.compile(r"this\s+shop\s+sells\s+many\s+antidotes\.", re.IGNORECASE)
_DIALOG_B = re.compile(r"no!\s+potions\s+are\s+all\s+sold\s+out\.", re.IGNORECASE)


def _bag(frame: Frame) -> dict[int, int]:
    """RAM 背包的数量映射。"""
    ram = frame.content.ram
    assert ram is not None
    return {item.item_id: item.quantity for item in ram.bag}


def _quantity(frame: Frame, item: int | None) -> int:
    """某道具数量；未知道具 ID 不可能匹配。"""
    return _bag(frame).get(item, 0) if item is not None else 0


def _in_battle(frame: Frame) -> bool:
    """RAM 战斗标志。"""
    return frame.content.ram is not None and frame.content.ram.in_battle


def _options(frame: Frame) -> bool:
    """该帧屏幕解码是否显示选项。"""
    return frame.from_decode and bool(frame.text.options)


def _full_party(frame: Frame) -> bool:
    """RAM 中队伍非空且全员满血。"""
    return _all_healed(frame)


@rule("walk_to_pallet")
def walk_to_pallet(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """依次经过 1 号道路、真新镇并进入大木研究所。"""
    frames = with_ram(target_frames(stream, sample))
    if len(frames) < 2:
        return unjudgeable("带 RAM 的帧不足两帧，无法核对起点与终局")
    start, final = frames[0], frames[-1]
    if start.content.facts.map_id != 1:
        return unjudgeable("开局地图不是常青市地图 1")
    i1 = next((i for i, frame in enumerate(frames) if frame.content.facts.map_id == 12), None)
    i2 = next(
        (
            i
            for i, frame in enumerate(frames)
            if i1 is not None and i > i1 and frame.content.facts.map_id == 0
        ),
        None,
    )
    i3 = next(
        (
            i
            for i, frame in enumerate(frames)
            if i2 is not None and i > i2 and frame.content.facts.map_id == 40
        ),
        None,
    )
    encounters = sum(
        1
        for previous, current in zip(frames, frames[1:], strict=False)
        if not _in_battle(previous) and _in_battle(current)
    )
    battle_frames = sum(_in_battle(frame) for frame in frames)
    metrics = f"遇敌次数 {encounters}，战斗内帧数 {battle_frames}"
    if i1 is None:
        return failed(f"从未到 1 号道路；{metrics}", start, final)
    if i2 is None:
        return failed(f"到了 1 号道路但没到真新镇；{metrics}", frames[i1], final)
    if i3 is None:
        return failed(f"到了真新镇但没进入大木研究所；{metrics}", frames[i2], final)
    if _in_battle(final) or _options(final):
        return failed(f"到了研究所但终局仍在战斗或停在选项里；{metrics}", frames[i3], final)
    return passed(
        f"依序到达地图 12、0、40；{metrics}", start, frames[i1], frames[i2], frames[i3], final
    )


@rule("heal_buy_return")
def heal_buy_return(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """治满队伍、买两颗球、回到起点且背包无额外变化。"""
    frames = with_ram(target_frames(stream, sample))
    pair = ends(frames)
    if pair is None:
        return unjudgeable("RAM 帧不足两帧")
    start, final = pair
    assert start.content.ram is not None and final.content.ram is not None
    if not any(0 < mon.hp < mon.max_hp for mon in start.content.ram.party):
        return unjudgeable("开局没有 HP 受伤的队员")
    heals = [
        i
        for i, frame in enumerate(frames)
        if frame.content.facts.map_id == 41 and _full_party(frame)
    ]
    buy_index = next(
        (
            i
            for i, frame in enumerate(frames)
            if _quantity(frame, _POKE_BALL) == _quantity(start, _POKE_BALL) + 2
        ),
        None,
    )
    final_bag, start_bag = _bag(final), _bag(start)
    changed = {
        item
        for item in set(final_bag) | set(start_bag)
        if item != 70 and final_bag.get(item, 0) != start_bag.get(item, 0)
    }
    if not heals:
        return failed("从未在地图 41 出现全员满血", start, final)
    if (
        _quantity(final, _POKE_BALL) != _quantity(start, _POKE_BALL) + 2
        or final.content.ram.money != start.content.ram.money - 400
    ):
        return failed("没有买到 2 个精灵球或花费不是 400", start, final)
    if changed - ({_POKE_BALL} if _POKE_BALL is not None else set()):
        return failed("背包除 item 70 与 2 个精灵球外还有变化", start, final)
    if buy_index is None or buy_index <= heals[0]:
        return failed("先买后治，购买成交帧没有晚于治疗帧", frames[heals[0]], final)
    if (
        final.content.place is None
        or start.content.place is None
        or (final.content.place.map_id, final.content.place.x, final.content.place.y)
        != (start.content.place.map_id, start.content.place.x, start.content.place.y)
        or _in_battle(final)
    ):
        return failed("没有回到起点格或终局仍在战斗", start, final)
    return passed(
        "先在中心治满、再买两球并回到起点", start, frames[heals[0]], frames[buy_index], final
    )


@rule("catch_then_heal")
def catch_then_heal(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """捕获新成员后再到中心治满，且离开捕获/命名状态。"""
    frames = with_ram(target_frames(stream, sample))
    pair = ends(frames)
    if pair is None:
        return unjudgeable("RAM 帧不足两帧")
    start, final = pair
    assert start.content.ram is not None and final.content.ram is not None
    caught = next(
        (
            i
            for i, frame in enumerate(frames)
            if len(frame.content.ram.party) == len(start.content.ram.party) + 1
        ),
        None,
    )
    defeated = [frame for frame in frames if _foe_hp(frame) == 0]
    if defeated:
        return failed("把对手打倒了：对手 HP 曾为 0", *defeated)
    if len(final.content.ram.party) != len(start.content.ram.party) + 1 or caught is None:
        return failed("没抓到：终局队伍人数未增加一只", start, final)
    heals = [
        i
        for i, frame in enumerate(frames)
        if frame.content.facts.map_id == 41 and _full_party(frame)
    ]
    if not heals:
        return failed("抓到后队伍没有在地图 41 治到全员满血", frames[caught], final)
    if heals[0] <= caught:
        return failed("先治后抓：治疗帧不晚于捕获成功帧", frames[heals[0]], frames[caught])
    naming = final.from_decode and "A B C D E F G H I" in final.content.facts.screen
    if _in_battle(final) or _options(final) or naming:
        return failed("终局仍在战斗、选项或起名界面", final)
    caught_text = next(
        (frame for frame in frames[: caught + 1] if ball_caught(frame)),
        None,
    )
    evidence = [start, frames[caught], frames[heals[0]], final]
    if caught_text is not None:
        evidence.append(caught_text)
    return passed("队伍人数证实捕获后到中心治满并正常退出", *evidence)


def _observation_dialogs(stream: RunStream, sample: EvalSample) -> list[tuple[str, float, str]]:
    """脚本逐键观察里的解码对话，按所属账事件时间返回 (uuid, time, text)。"""
    episodes = (
        stream.run_episodes()
        if sample.granularity == "run"
        else stream.episodes_for(sample.sample_id)
    )
    records: list[tuple[float, str, str]] = []
    for event in stream.in_episodes(episodes, "write_act_memory"):
        content = event.content.model_dump(mode="python")
        raw_frames = [content["before"], *content.get("observations", []), content["after"]]
        for observed in raw_frames:
            dialog = observed.get("dialog_text", "")
            if dialog:
                records.append((event.ended_at, event.uuid, str(dialog)))
    records.sort(key=lambda item: (item[0], item[1]))
    return [(uuid, timestamp, dialog) for timestamp, uuid, dialog in records]


def _observation_maps(stream: RunStream, sample: EvalSample) -> list[tuple[str, int]]:
    """脚本逐键观察中的位置地图编号，按账本顺序返回 (事件 UUID, map_id)。"""
    episodes = (
        stream.run_episodes()
        if sample.granularity == "run"
        else stream.episodes_for(sample.sample_id)
    )
    records: list[tuple[float, str, int]] = []
    for event in stream.in_episodes(episodes, "write_act_memory"):
        content = event.content.model_dump(mode="python")
        raw_frames = [content["before"], *content.get("observations", []), content["after"]]
        for observed in raw_frames:
            place = observed.get("place")
            if isinstance(place, dict) and isinstance(place.get("map_id"), int):
                records.append((event.ended_at, event.uuid, place["map_id"]))
    records.sort(key=lambda item: (item[0], item[1]))
    return [(uuid, map_id) for _, uuid, map_id in records]


@rule("customer_hint_purchase")
def customer_hint_purchase(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """两句顾客提示、中心治疗、最后只买一件解毒药。"""
    frames = with_ram(target_frames(stream, sample))
    pair = ends(frames)
    if pair is None:
        return unjudgeable("RAM 帧不足两帧")
    start, final = pair
    assert start.content.ram is not None and final.content.ram is not None
    event_time = {event.uuid: event.ended_at for event in stream.events}
    decoded_dialogs: list[tuple[str, float, str]] = [
        (frame.uuid, event_time.get(frame.uuid, float(frame.step)), frame.text.dialog_text)
        for frame in frames
        if frame.from_decode
    ]
    decoded_dialogs.extend(_observation_dialogs(stream, sample))
    decoded_dialogs.sort(key=lambda item: (item[1], item[0]))
    first_a = next(
        (
            (uuid, timestamp)
            for uuid, timestamp, text in decoded_dialogs
            if _DIALOG_A.search(" ".join(text.casefold().split()))
        ),
        None,
    )
    first_b = next(
        (
            (uuid, timestamp)
            for uuid, timestamp, text in decoded_dialogs
            if _DIALOG_B.search(" ".join(text.casefold().split()))
        ),
        None,
    )
    if first_a is None or first_b is None:
        return failed("缺一句顾客台词：需要两句指定解码提示", start, final)
    heals = [
        i
        for i, frame in enumerate(frames)
        if frame.content.facts.map_id == 41 and _full_party(frame)
    ]
    if not heals:
        return failed("队伍没有在地图 41 治到全员满血", start, final)
    if _quantity(final, _ANTIDOTE) != _quantity(start, _ANTIDOTE) + 1 or any(
        _quantity(final, item) != _quantity(start, item)
        for item in (_POKE_BALL, _PARLYZ_HEAL, _BURN_HEAL)
    ):
        return failed("买错东西或多买：终局道具数量不符合只买 1 个 ANTIDOTE", start, final)
    if final.content.ram.money != start.content.ram.money - 100:
        return failed("购买 ANTIDOTE 后钱数不是减少 100", start, final)
    buy_index = next(
        (
            i
            for i, frame in enumerate(frames)
            if _quantity(frame, _ANTIDOTE) == _quantity(start, _ANTIDOTE) + 1
        ),
        None,
    )
    if (
        buy_index is None
        or max(first_a[1], first_b[1])
        >= event_time.get(frames[heals[0]].uuid, float(frames[heals[0]].step))
        or buy_index <= heals[0]
    ):
        return failed("顺序不对：两句顾客台词、治疗、成交必须依次发生", frames[heals[0]], final)
    return passed(
        "先听到两位顾客提示，再治满队伍并买 1 个 ANTIDOTE",
        frames[heals[0]],
        frames[buy_index],
        final,
    )


@rule("cure_poison_budget")
def cure_poison_budget(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """不进中心，花 100–150 元后治好开局中毒的第二只。"""
    frames = with_ram(target_frames(stream, sample))
    pair = ends(frames)
    if pair is None:
        return unjudgeable("RAM 帧不足两帧")
    start, final = pair
    assert start.content.ram is not None and final.content.ram is not None
    if len(start.content.ram.party) < 2 or start.content.ram.party[1].status != "PSN":
        return unjudgeable("开局第二只不是中毒状态")
    if len(final.content.ram.party) < 2 or final.content.ram.party[1].status != "ok":
        return failed("第二只中毒尚未治好", start, final)
    center_frames = [frame for frame in frames if frame.content.facts.map_id == 41]
    center_observations = [
        uuid for uuid, map_id in _observation_maps(stream, sample) if map_id == 41
    ]
    if center_frames or center_observations:
        return CheckVerdict(
            outcome="fail",
            evidence=[frame.uuid for frame in center_frames] + center_observations,
            reason="执行线曾进入宝可梦中心地图 41",
        )
    spent = start.content.ram.money - final.content.ram.money
    if not 100 <= spent <= 150:
        return failed(f"总花费 {spent} 不在 100–150 范围内", start, final)
    paid = next(
        (
            i
            for i, frame in enumerate(frames)
            if frame.content.ram and frame.content.ram.money < start.content.ram.money
        ),
        None,
    )
    cured = next(
        (
            i
            for i, frame in enumerate(frames)
            if len(frame.content.ram.party) > 1 and frame.content.ram.party[1].status == "ok"
        ),
        None,
    )
    if paid is None or cured is None or paid >= cured:
        return failed("先治后花钱：状态恢复必须晚于首次钱数减少", start, final)
    return passed(
        f"未进中心，先花费 {spent} 元后治好第二只", start, frames[paid], frames[cured], final
    )


__all__ = [
    "catch_then_heal",
    "cure_poison_budget",
    "customer_hint_purchase",
    "heal_buy_return",
    "walk_to_pallet",
]
