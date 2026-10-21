"""治疗起点的可判定性检查；从真实世界读取，不采信样本描述。"""

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.dataset.errors import DatasetError
from pokemon_agent.world import RamReadout, TaskObservation, TaskScene


def validate_start(
    sample: EvalSample, ram: RamReadout | None, observation: TaskObservation | None = None
) -> None:
    """治疗须有伤员，取消购买须在确认框；不符时抛 DatasetError，拒绝发布假起点。"""
    if sample.check_id == "party_healed" and (
        ram is None or not ram.party or not any(0 < mon.hp < mon.max_hp for mon in ram.party)
    ):
        raise DatasetError(f"{sample.sample_id}：治疗起点必须至少有一只存活且受伤的宝可梦")
    if sample.check_id == "shop_cancelled" and (
        ram is None
        or observation is None
        or observation.scene is not TaskScene.SHOP_ITEMS
        or ram.decoded.options != ["YES", "NO"]
    ):
        raise DatasetError(f"{sample.sample_id}：取消购买起点必须在商店购买确认 YES/NO")
