"""`action_limits`、`loop`、`budget` 三段：动作输出上限、循环控制、运行预算。"""

from pydantic import Field, model_validator

from .base import Section


class ActionLimitsConfig(Section):
    """模型一次决策能写多大：最多几段、一段最多连按几次。prompt 渲染与 tool 校验同源。"""

    max_segments: int = Field(gt=0)
    max_times: int = Field(gt=0)


class LoopConfig(Section):
    """三层停摆上限、规划建议量，以及 run / episode 图的 superstep 闸门（大数，不是预算）。

    两个 `freeze_*` 是**评测专用**的规划层冻结开关（默认关）：关掉规划层的那一层不再调用
    模型、不写规划账，只按事先给定的表逐条派发（语义见 `harness/run/plan_run` 与
    `harness/episode/plan_episode`）。
    """

    act_stall_limit: int = Field(gt=0)
    episode_stall_limit: int = Field(gt=0)
    run_stall_limit: int = Field(gt=0)
    episode_max_tasks_per_plan: int = Field(gt=0)
    plan_max_new_goals: int = Field(gt=0)
    episode_recursion_limit: int = Field(gt=0)
    run_recursion_limit: int = Field(gt=0)
    freeze_run_plan: bool
    freeze_episode_plan: bool


class BudgetConfig(Section):
    """分层运行预算；重试与 plan 时限已分别并入 `retry` 与 `models.plan`，此处不再重复。"""

    max_episodes: int = Field(gt=0)
    max_total_actions: int | None = Field(gt=0)
    wall_clock_s: float | None = Field(gt=0, allow_inf_nan=False)
    reserve_s: float = Field(ge=0, allow_inf_nan=False)
    episode_max_tasks: int = Field(gt=0)
    max_decompositions: int = Field(gt=0)
    max_planning_rounds: int = Field(gt=0)
    task_max_steps: int = Field(gt=0)
    min_request_s: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_wall_clock(self) -> "BudgetConfig":
        """有限总时长必须容纳收尾预留。"""
        if self.wall_clock_s is not None and self.wall_clock_s <= self.reserve_s:
            raise ValueError("wall_clock_s must exceed reserve_s")
        return self
