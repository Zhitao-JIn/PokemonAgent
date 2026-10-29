"""按评测档位推导单样本运行预算。"""

from __future__ import annotations

from collections.abc import Mapping
from math import ceil
from typing import Any

from evals.agent_short_goal_run.dataset.schemas import EvalSample

DEFAULTS = {
    "seconds_per_action": 40,
    "reserve_s": 120,
    "timeout_margin_s": 300,
    "long_max_episodes": 6,
}


def derive_sample_budget(sample: EvalSample, config: Mapping[str, Any]) -> dict[str, int]:
    """按样本档位生成有效预算；短期原样继承配置预算与 timeout。"""
    derivation = {**DEFAULTS, **dict(config.get("budget_derivation", {}))}
    seconds = int(derivation["seconds_per_action"])
    if seconds <= 0:
        raise ValueError("budget_derivation.seconds_per_action 必须为正数")
    budget = dict(config["budget"])
    if sample.tier == "short":
        return {
            "max_total_actions": int(budget["max_total_actions"]),
            "wall_clock_s": int(budget["wall_clock_s"]),
            "timeout": int(config["timeout"]),
            "max_episodes": int(budget["max_episodes"]),
        }
    wall_clock = ceil(sample.max_steps * seconds) + int(derivation["reserve_s"])
    return {
        "max_total_actions": sample.max_steps,
        "wall_clock_s": wall_clock,
        "timeout": wall_clock + int(derivation["timeout_margin_s"]),
        "max_episodes": len(sample.goals)
        if sample.tier == "mid"
        else int(derivation["long_max_episodes"]),
    }


def sample_timeout(sample: EvalSample, config: Mapping[str, Any]) -> int:
    """返回 solver 子进程应使用的该样本进程时限。"""
    return derive_sample_budget(sample, config)["timeout"]


__all__ = ["DEFAULTS", "derive_sample_budget", "sample_timeout"]
