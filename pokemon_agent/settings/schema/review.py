"""`review` 段：复核席模式、链路地址、启用层与 AI 席预算。

`mode` 取代"有地址就启用"的隐式规则：`off` 无头（NullReviewer），其余三种经
`link_url` 连独立 reviewer 进程；reviewer 进程读同一份配置，模式与地址只写一处。
"""

from typing import Literal

from pydantic import Field, model_validator

from .base import Section


class ReviewConfig(Section):
    """复核链路配置。"""

    mode: Literal["off", "human", "ai", "both"]
    link_url: str | None = Field(min_length=1)
    link_lost_timeout_s: float | None = Field(gt=0, allow_inf_nan=False)
    layers: tuple[Literal["run", "episode", "task"], ...]
    ai_inject_max_rounds: int = Field(gt=0)
    ai_countdown_s: float = Field(gt=0, allow_inf_nan=False)
    agent_max_tool_calls: int = Field(gt=0)
    agent_turn_budget_s: float = Field(gt=0, allow_inf_nan=False)
    agent_model: str = Field(min_length=1)
    agent_base_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_mode(self) -> "ReviewConfig":
        """非 off 模式必须有链路地址；启用层不得重复。"""
        if self.mode != "off" and self.link_url is None:
            raise ValueError("review.link_url is required when review.mode is not 'off'")
        if len(set(self.layers)) != len(self.layers):
            raise ValueError("review.layers must not contain duplicates")
        return self
