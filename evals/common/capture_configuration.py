"""本轮重采的显式有效预算与配置；配置与代码指纹共同固定执行口径。"""

from pathlib import Path

from evals.common.overlay import eval_overlay, write_overlay
from evals.runconfig import load_config
from pokemon_agent.settings import AppConfig, BudgetConfig
from pokemon_agent.settings import load_config as load_app_config

CAPTURE_PLANNING_ROUNDS = 6
CAPTURE_DECOMPOSITIONS = 12


def capture_overlay() -> dict[str, object]:
    """评测配置覆盖层：`evals/config.json` 的预算 / 型号 / 后端，加上采集专用的规划轮数。"""
    overlay = eval_overlay(load_config())
    budget = dict(overlay["budget"])
    budget["max_planning_rounds"] = CAPTURE_PLANNING_ROUNDS
    budget["max_decompositions"] = CAPTURE_DECOMPOSITIONS
    return {**overlay, "budget": budget}


def capture_app_config(directory: Path) -> AppConfig:
    """把采集覆盖层落盘到 `directory` 并与保底合并，返回生效配置（同时校验它合法）。"""
    path, _digest = write_overlay(directory / "capture_overlay.json", capture_overlay())
    return load_app_config(path).config


def capture_budget() -> BudgetConfig:
    """保留总局数、动作和时间预算，显式设置新规划轮数；与保底合并后的完整预算。"""
    return BudgetConfig.model_validate(
        {**load_app_config().config.budget.model_dump(), **capture_overlay()["budget"]}
    )
