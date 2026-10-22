"""按冻结 judge 请求中的完整历史裁定 CP2 待审样本。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Adjudication:
    """历史裁定结果及可在请求历史中复核的证据。"""

    achieved: bool
    negative_mode: str | None
    evidence_locator: str
    evidence_summary: str


def _observations(row: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    observations = []
    for index, memory in enumerate(row["request"]["history"]):
        for side in ("before", "after"):
            state = memory.get(side) or {}
            observations.append(
                (f"request.history[{index}].{side}", state, state.get("facts") or {})
            )
    return observations


def _coordinates(where: object) -> tuple[int, int] | None:
    if not isinstance(where, str):
        return None
    match = re.search(r"x=(\d+)\s+y=(\d+)", where)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _facing(criteria: str) -> str | None:
    match = re.search(r"facing\s*(?:为|朝)\s*(north|south|east|west|北|南|东|西)", criteria)
    if match is None:
        return None
    return {"北": "north", "南": "south", "东": "east", "西": "west"}.get(
        match.group(1), match.group(1)
    )


def _decision(
    row: dict[str, Any],
    achieved: bool,
    summary: str,
    locator: str | None = None,
) -> Adjudication:
    criteria = row["criteria"]
    family = row["goal_family"]
    mode: str | None = None
    if not achieved:
        if "where" in criteria or "相邻" in criteria:
            target = re.search(r"x=(\d+)\s+y=(\d+)", criteria)
            target_position = (
                (int(target.group(1)), int(target.group(2))) if target is not None else None
            )
            near_target = any(
                _coordinates(facts.get("where")) == target_position
                for _, _, facts in _observations(row)
            )
            mode = "near_miss" if near_target and _facing(criteria) else "wrong_map_or_location"
        elif "投球" in criteria or "精灵球" in criteria:
            partial_throw = any(
                facts.get("cursor") in {"POKé BALL", "POKEMON BALL", "POKéMON BALL"}
                or "all right!" in str(facts.get("dialog_text", "")).lower()
                for _, _, facts in _observations(row)
            )
            mode = "near_miss" if partial_throw else "required_state_missing"
        elif "店员" in criteria or "对话框" in criteria:
            has_partial_dialogue = any(
                "shop" in str(facts.get("dialog_text", "")).lower()
                for _, _, facts in _observations(row)
            )
            mode = "near_miss" if has_partial_dialogue else "wrong_dialogue_or_event"
        elif row["suggested_achieved"] is not None and family == "battle_or_encounter":
            mode = "required_state_missing"
        else:
            mode = {
                "navigation": "wrong_map_or_location",
                "interaction": "wrong_dialogue_or_event",
                "party_or_inventory": "required_state_missing",
                "battle_or_encounter": "required_state_missing",
                "other": "other",
            }[family]
    return Adjudication(
        achieved=achieved,
        negative_mode=mode,
        evidence_locator=locator or "request.history",
        evidence_summary=summary,
    )


def adjudicate_candidate(row: dict[str, Any]) -> Adjudication:
    """依据当前状态或历史中已发生的目标事件裁定一条非机械样本。"""
    criteria = row["criteria"]
    observations = _observations(row)
    if not observations:
        raise ValueError(f"{row['candidate_id']} has no request history")

    if "foe_hp" in criteria:
        threshold = re.search(r"低于\s*(\d+)", criteria)
        last_facts = row["request"]["history"][-1].get("after", {}).get("facts", {})
        hp = re.match(r"(\d+)", str(last_facts.get("foe_hp", "")))
        reached = bool(threshold and hp and int(hp.group(1)) < int(threshold.group(1)))
        return _decision(
            row,
            reached,
            f"请求时最后状态 foe_hp={last_facts.get('foe_hp')!r}; criteria={criteria}",
            f"request.history[{len(row['request']['history']) - 1}].after.facts.foe_hp",
        )

    if "不再是 battle" in criteria or "scene 不再是 battle" in criteria:
        was_in_battle = False
        for locator, state, facts in observations:
            dialog = str(facts.get("dialog_text", "")).lower()
            scene = state.get("scene") or facts.get("scene")
            if isinstance(scene, str) and scene.startswith("battle"):
                was_in_battle = True
            elif was_in_battle and scene in {"walk", "dialog", "shop", ""}:
                return _decision(
                    row,
                    True,
                    f"该历史状态 scene={state.get('scene')!r}，战斗已结束",
                    f"{locator}.scene",
                )
            if any(
                term in dialog for term in ("fainted!", "was caught!", "broke free!", "got away!")
            ):
                return _decision(
                    row, True, f"战斗结束文字：{dialog!r}", f"{locator}.facts.dialog_text"
                )
        return _decision(row, False, "完整请求历史中没有战斗退出状态或结束文字")

    coordinates = re.search(r"x=(\d+)\s+y=(\d+)", criteria)
    if coordinates:
        target = (int(coordinates.group(1)), int(coordinates.group(2)))
        facing = _facing(criteria)
        adjacent = "相邻" in criteria and "facing" in criteria
        for locator, _, facts in observations:
            actual = _coordinates(facts.get("where"))
            matches_location = actual == target
            if adjacent and actual is not None:
                matches_location = matches_location or (
                    abs(actual[0] - target[0]) + abs(actual[1] - target[1]) == 1
                )
            if matches_location and (facing is None or facts.get("facing") == facing):
                return _decision(
                    row,
                    True,
                    f"历史位置 {actual} facing={facts.get('facing')!r} 满足目标 {target}"
                    + (f" facing={facing}" if facing else ""),
                    f"{locator}.facts.where",
                )
        return _decision(
            row,
            False,
            f"完整请求历史没有达到位置 {target}" + (f" facing={facing}" if facing else ""),
        )

    if "光标在 ITEM" in criteria:
        for locator, _, facts in observations:
            if facts.get("cursor") == "ITEM" and set(facts.get("options") or []) >= {
                "FIGHT",
                "PKMN",
                "ITEM",
                "RUN",
            }:
                return _decision(
                    row, True, "历史战斗选单中光标到达 ITEM", f"{locator}.facts.cursor"
                )
        return _decision(row, False, "完整请求历史中 ITEM 从未成为当前选项")

    if "HEAL" in criteria and "CANCEL" in criteria:
        for locator, _, facts in observations:
            if {"HEAL", "CANCEL"} <= set(facts.get("options") or []) and facts.get(
                "cursor"
            ) == "HEAL":
                return _decision(
                    row,
                    True,
                    "历史选项同时含 HEAL/CANCEL 且光标在 HEAL",
                    f"{locator}.facts.options",
                )
        return _decision(row, False, "完整请求历史中未同时出现 HEAL/CANCEL 且光标在 HEAL")

    if "店员" in criteria or "BUY / SELL / QUIT" in criteria:
        dialog_hits = [
            index
            for index, (_, _, facts) in enumerate(observations)
            if "shop" in str(facts.get("dialog_text", "")).lower()
        ]
        menu_hits = [
            index
            for index, (_, _, facts) in enumerate(observations)
            if set(facts.get("options") or []) & {"BUY", "SELL", "QUIT"}
        ]
        if "且之后" in criteria or "之后出现" in criteria:
            pair = next(((d, m) for d in dialog_hits for m in menu_hits if m > d), None)
            if pair is not None:
                locator = observations[pair[1]][0] + ".facts.options"
                return _decision(row, True, "历史先出现店员对话，之后出现商店选项", locator)
            return _decision(
                row,
                False,
                "完整请求历史未同时出现店员对话及其后的 BUY/SELL/QUIT 选项",
            )
        if dialog_hits or menu_hits:
            index = dialog_hits[0] if dialog_hits else menu_hits[0]
            field = "dialog_text" if dialog_hits else "options"
            return _decision(
                row, True, "历史中出现店员对话或商店选项", f"{observations[index][0]}.facts.{field}"
            )
        return _decision(row, False, "完整请求历史中未出现店员对话或商店选项")

    if "治疗完成" in criteria or "We hope to see you again" in criteria:
        terms = ("see you again", "恢复", "欢迎再来")
        for locator, _, facts in observations:
            dialog = str(facts.get("dialog_text", "")).lower()
            if any(term in dialog for term in terms):
                return _decision(
                    row, True, f"治疗完成文字：{dialog!r}", f"{locator}.facts.dialog_text"
                )
        return _decision(row, False, "完整请求历史未出现治疗完成文字")

    if "治疗进行/完成" in criteria:
        for locator, _, facts in observations:
            dialog = str(facts.get("dialog_text", "")).lower()
            if "thank you! your pokémon are" in dialog or "have been healed" in dialog:
                return _decision(
                    row, True, f"治疗流程文字：{dialog!r}", f"{locator}.facts.dialog_text"
                )
        return _decision(row, False, "完整请求历史未出现治疗进行或完成文字")

    if "投球结果" in criteria or "was caught!" in criteria or "broke free!" in criteria:
        for locator, _, facts in observations:
            dialog = str(facts.get("dialog_text", "")).lower()
            if "was caught!" in dialog or "broke free!" in dialog:
                return _decision(
                    row, True, f"投球结果文字：{dialog!r}", f"{locator}.facts.dialog_text"
                )
        return _decision(row, False, "完整请求历史没有 caught/broke free 结果文字")

    if "投球" in criteria or "精灵球" in criteria or "投出球" in criteria:
        for locator, _, facts in observations:
            dialog = str(facts.get("dialog_text", "")).lower()
            if "all right!" in dialog or "broke free" in dialog or "used a poké ball" in dialog:
                return _decision(
                    row, True, f"历史投球提示文字：{dialog!r}", f"{locator}.facts.dialog_text"
                )
        return _decision(row, False, "历史只显示选中精灵球，未显示确认使用或投球提示")

    if row["suggested_achieved"] is not None:
        return _decision(
            row,
            bool(row["suggested_achieved"]),
            "已复核 CP2 建议与请求历史相符：" + str(row["evidence"][0]["summary"]),
            row["evidence"][0]["locator"],
        )
    raise ValueError(f"unsupported criteria for {row['candidate_id']}: {criteria}")


__all__ = ["Adjudication", "adjudicate_candidate"]
