"""本轮重采的显式有效预算；配置与代码指纹共同固定执行口径。"""

from evals.runconfig import load_config
from pokemon_agent.run_budget import RunBudget
from pokemon_agent.run_config import load_run_config


def capture_budget() -> RunBudget:
    """保留总局数、动作和时间预算，显式设置新规划轮数。"""
    return RunBudget.model_validate(
        {
            **load_run_config(None).budget.model_dump(),
            **load_config()["budget"],
            "max_planning_rounds": 6,
            "max_decompositions": 12,
        }
    )
