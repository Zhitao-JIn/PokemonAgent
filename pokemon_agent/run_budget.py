"""分层运行预算的不可变数据模型；字段单位由各层显式消费。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunBudget(BaseModel):
    """装配期校验预算；未知字段、错误类型和无效数值直接拒绝。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_episodes: int = Field(gt=0)
    max_total_actions: int | None = Field(default=None, gt=0)
    wall_clock_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reserve_s: float = Field(ge=0, allow_inf_nan=False)
    episode_max_tasks: int = Field(gt=0)
    max_decompositions: int = Field(gt=0)
    task_default_steps: int = Field(gt=0)
    task_max_steps: int = Field(gt=0)
    min_request_s: float = Field(gt=0, allow_inf_nan=False)
    brain_max_attempts: int = Field(gt=0)
    plan_thinking: bool
    plan_max_tokens: int = Field(gt=0)
    plan_timeout_s: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_limits(self) -> "RunBudget":
        """默认任务预算不能超过硬上限，有限总时长必须容纳收尾预留。"""
        if self.task_default_steps > self.task_max_steps:
            raise ValueError("task_default_steps must not exceed task_max_steps")
        if self.wall_clock_s is not None and self.wall_clock_s <= self.reserve_s:
            raise ValueError("wall_clock_s must exceed reserve_s")
        if self.plan_timeout_s < self.min_request_s:
            raise ValueError("plan_timeout_s must be at least min_request_s")
        return self
