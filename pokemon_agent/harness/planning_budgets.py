"""把生效配置与当前计数装成模型可见素材；不读取全局配置或改变状态。"""

from typing import Literal

from pokemon_agent.schemas.harness.domain.budget_allowance import BudgetAllowance
from pokemon_agent.settings.schema.loop import BudgetConfig


def configured(
    config: BudgetConfig,
    field: str,
    scope: Literal["run", "episode", "task"],
    unit: Literal["episodes", "tasks", "actions", "rounds", "seconds"],
    used: float = 0,
) -> BudgetAllowance:
    """调用方保证字段属于BudgetConfig；返回对应配置硬限及真实用量。"""
    return BudgetAllowance(
        kind="hard",
        scope=scope,
        unit=unit,
        source=f"budget.{field}",
        limit=getattr(config, field),
        used=used,
    )


def inherited(
    scope: Literal["run", "episode", "task"],
    unit: Literal["episodes", "tasks", "actions", "rounds", "seconds"],
    limit: int,
    used: int,
) -> BudgetAllowance:
    """父级建议不覆盖配置，超出建议后的真实用量仍可见。"""
    return BudgetAllowance(
        kind="advisory",
        scope=scope,
        unit=unit,
        source="parent.budget.limit",
        limit=limit,
        used=used,
    )


def run_budgets(
    config: BudgetConfig, *, episodes: int, actions: int, rounds: int
) -> list[BudgetAllowance]:
    """run规划看见本run余量和下层每次执行硬限；无父级建议额度。"""
    return [
        configured(config, "max_episodes", "run", "episodes", episodes),
        configured(config, "max_total_actions", "run", "actions", actions),
        configured(config, "max_planning_rounds", "run", "rounds", rounds),
        configured(config, "episode_max_tasks", "episode", "tasks"),
        configured(config, "task_max_steps", "task", "actions"),
    ]


def episode_budgets(
    config: BudgetConfig, *, advice: int, tasks: int, rounds: int
) -> list[BudgetAllowance]:
    """拆解看见父级建议与本局硬限，以及每个子task的配置硬限。"""
    return [
        inherited("episode", "tasks", advice, tasks),
        configured(config, "episode_max_tasks", "episode", "tasks", tasks),
        configured(config, "max_decompositions", "episode", "rounds", rounds),
        configured(config, "task_max_steps", "task", "actions"),
    ]


def task_budgets(config: BudgetConfig, *, advice: int, actions: int) -> list[BudgetAllowance]:
    """动作决策看见父级建议与每task硬限，两种额度共用实际动作计数。"""
    return [
        inherited("task", "actions", advice, actions),
        configured(config, "task_max_steps", "task", "actions", actions),
    ]


def shared_budgets(
    config: BudgetConfig, *, action_limit: int | None, actions: int, remaining_s: float | None
) -> list[BudgetAllowance]:
    """下层继承本次派发剩余全局额度；时间扣除统一收尾预留。"""
    return [
        BudgetAllowance(
            kind="hard",
            scope="run",
            unit="actions",
            source="budget.max_total_actions:dispatch_remaining",
            limit=action_limit,
            used=actions,
        ),
        time_budget(config, remaining_s),
    ]


def time_budget(config: BudgetConfig, remaining_s: float | None) -> BudgetAllowance:
    """模型可用时间与Deadline同源，统一扣除配置收尾预留。"""
    return BudgetAllowance(
        kind="hard",
        scope="run",
        unit="seconds",
        source="budget.wall_clock_s-minus-reserve_s",
        limit=None if config.wall_clock_s is None else config.wall_clock_s - config.reserve_s,
        used=0
        if remaining_s is None or config.wall_clock_s is None
        else max(0, config.wall_clock_s - remaining_s),
    )
