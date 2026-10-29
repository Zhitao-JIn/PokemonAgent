"""`AppConfig`：全项目唯一的配置根，由 `default.json` 与覆盖文件合并而来。

按"谁消费"分段；跨段约束在这里集中校验。`eval` 段是 evals 包的专属配置，本模块
不认识其内容、只透传，由 evals 自己校验（规范里登记的豁免，见 CHANGELOG 对应条目）。
"""

from typing import Any

from pydantic import Field, model_validator

from .base import Section
from .deployment import (
    DebugSection,
    PathsSection,
    RunSection,
    ServicesSection,
    TraceSection,
)
from .loop import ActionLimitsConfig, BudgetConfig, LoopConfig
from .memory import MemoryConfig
from .models import ModelsConfig
from .prompt import PromptSection
from .retry import RequestTimeoutsConfig, RetryConfig
from .review import ReviewConfig


class AppConfig(Section):
    """生效配置。每个字段对应 `default.json` 的一个顶层键，零缺省。"""

    run: RunSection
    models: ModelsConfig
    prompt: PromptSection
    retry: RetryConfig
    request_timeouts_s: RequestTimeoutsConfig
    action_limits: ActionLimitsConfig
    loop: LoopConfig
    budget: BudgetConfig
    memory: MemoryConfig
    review: ReviewConfig
    trace: TraceSection
    paths: PathsSection
    services: ServicesSection
    debug: DebugSection
    eval: dict[str, Any] | None = Field()

    @model_validator(mode="after")
    def validate_cross_section(self) -> "AppConfig":
        """跨段约束：plan 时限不低于最小有用时长；图片帽容得下一个 task 的全部帧。"""
        if self.models.plan.timeout_s < self.budget.min_request_s:
            raise ValueError("models.plan.timeout_s must be at least budget.min_request_s")
        if self.memory.scope_image_cap < self.budget.task_max_steps + 1:
            raise ValueError(
                "memory.scope_image_cap must be at least budget.task_max_steps + 1 "
                f"({self.budget.task_max_steps + 1})"
            )
        return self
