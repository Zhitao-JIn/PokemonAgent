"""起点条件检查；运行时只使用世界公开的 RAM 读数与 task 观测。"""

import re

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.dataset.errors import DatasetError
from pokemon_agent.world import RamReadout, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import BattleMenuView

PREFLIGHT_CHECK_IDS = frozenset(
    {
        "party_healed",
        "shop_cancelled",
        "walk_to_pallet",
        "heal_buy_return",
        "catch_then_heal",
        "customer_hint_purchase",
        "cure_poison_budget",
        "leave_pallet_town",
    }
)

POKE_BALL = 4
POTION = 20
PARCEL = 70


def validate_start(
    sample: EvalSample, ram: RamReadout | None, observation: TaskObservation | None = None
) -> None:
    """拒绝不满足样本起点契约的真实世界状态。"""
    check_id = sample.check_id
    place = observation.place if observation is not None else None
    if check_id == "party_healed" and (
        ram is None or not ram.party or not any(0 < mon.hp < mon.max_hp for mon in ram.party)
    ):
        raise DatasetError(f"{sample.sample_id}：治疗起点必须至少有一只存活且受伤的宝可梦")
    if check_id == "shop_cancelled" and (
        ram is None
        or observation is None
        or observation.scene is not TaskScene.SHOP_ITEMS
        or ram.decoded.options != ["YES", "NO"]
    ):
        raise DatasetError(f"{sample.sample_id}：取消购买起点必须在商店购买确认 YES/NO")
    if check_id == "walk_to_pallet" and (
        ram is None
        or observation is None
        or place is None
        or place.map_id != 1
        or observation.scene is not TaskScene.WALK
        or ram.in_battle
        or len(ram.party) != 2
        or any(mon.hp <= 0 for mon in ram.party)
    ):
        raise DatasetError(f"{sample.sample_id}：步行起点须在地图 1 行走，且队伍两只全员存活")
    if check_id == "heal_buy_return" and (
        ram is None
        or observation is None
        or place is None
        or place.map_id != 1
        or observation.scene is not TaskScene.WALK
        or not ram.party
        or not 0 < ram.party[0].hp < ram.party[0].max_hp
        or _quantity(ram, POKE_BALL) != 4
        or ram.money != 2000
    ):
        raise DatasetError(f"{sample.sample_id}：治疗购买起点的地图、首只 HP、精灵球或金钱不符")
    if check_id == "catch_then_heal":
        battle = observation.takeover if observation is not None else None
        if (
            ram is None
            or observation is None
            or not ram.in_battle
            or observation.scene is not TaskScene.BATTLE_MENU
            or not isinstance(battle, BattleMenuView)
            or battle.trainer
            or not ram.party
            or not 0 < ram.party[0].hp < ram.party[0].max_hp
            or battle.mine.hp != ram.party[0].hp
            or battle.mine.max_hp != ram.party[0].max_hp
            or not _decoded_hp_matches(observation, ram.party[0].hp, ram.party[0].max_hp)
            or _quantity(ram, POKE_BALL) < 1
        ):
            raise DatasetError(f"{sample.sample_id}：抓捕起点须为野生战斗，己方受伤读数一致且有球")
    if check_id == "customer_hint_purchase" and (
        ram is None
        or place is None
        or place.map_id != 42
        or ram.money != 3000
        or _quantity(ram, PARCEL) != 0
    ):
        raise DatasetError(f"{sample.sample_id}：商店起点须在地图 42、钱 3000 且没有包裹")
    if check_id == "cure_poison_budget" and (
        ram is None
        or place is None
        or place.map_id != 1
        or len(ram.party) < 2
        or ram.party[1].status != "PSN"
        or ram.money != 2000
        or _quantity(ram, POTION) < 1
    ):
        raise DatasetError(
            f"{sample.sample_id}：中毒起点须在地图 1、第二只中毒、钱 2000 且有 POTION"
        )
    if check_id == "leave_pallet_town" and (
        ram is None
        or observation is None
        or place is None
        or place.map_id != 38
        or observation.scene is not TaskScene.WALK
        or ram.in_battle
        or ram.party
        or ram.bag
        or ram.money != 3000
    ):
        raise DatasetError(
            f"{sample.sample_id}：长期起点须在卧室地图 38 行走，未战斗、队伍与背包为空、钱 3000"
        )


def _quantity(ram: RamReadout, item_id: int) -> int:
    return sum(item.quantity for item in ram.bag if item.item_id == item_id)


def _decoded_hp_matches(observation: TaskObservation, hp: int, max_hp: int) -> bool:
    """Require a screen-decoded HP fraction matching the first party member."""
    fractions = re.findall(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", observation.facts.screen)
    return (str(hp), str(max_hp)) in fractions


__all__ = ["PREFLIGHT_CHECK_IDS", "validate_start"]
