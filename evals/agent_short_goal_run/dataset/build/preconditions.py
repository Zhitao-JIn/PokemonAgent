"""治疗起点的可判定性检查；从真实世界读取，不采信样本描述。"""

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.dataset.errors import DatasetError
from pokemon_agent.world import RamReadout


def validate_start(sample: EvalSample, ram: RamReadout | None) -> None:
    """治疗必须从有存活伤员的队伍开始；无读数、空队伍或满血抛 DatasetError。"""
    if sample.check_id != "party_healed":
        return
    if ram is None or not ram.party or not any(0 < mon.hp < mon.max_hp for mon in ram.party):
        raise DatasetError(f"{sample.sample_id}：治疗起点必须至少有一只存活且受伤的宝可梦")
