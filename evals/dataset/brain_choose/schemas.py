"""单步决策冻结契约：生产请求与只供评分读取的可接受动作集合。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world import TaskScene


class ActionMatcher(BaseModel):
    """按键或脚本匹配条件恰好取一；次数只约束按键，参数只约束脚本。"""

    key: str | None = Field(default=None, min_length=1)
    max_times: int | None = Field(default=None, ge=1)
    script: str | None = Field(default=None, min_length=1)
    args: dict[str, str | int] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ActionMatcher:
        """外部冻结记录形状无效时抛 ValidationError，不依赖可被优化掉的 assert。"""
        if (self.key is not None) == (self.script is not None):
            raise ValueError("key 与 script 必须恰好一个非空")
        if self.max_times is not None and self.key is None:
            raise ValueError("max_times 仅可用于 key")
        if self.args is not None and self.script is None:
            raise ValueError("args 仅可用于 script")
        return self


class ChooseCase(BaseModel):
    """一个冻结现场；标签和来源说明只进评分，不进 chooser 请求。"""

    case_id: str
    request: FromHarnessToBrainToolChooseOnceReq
    acceptable: list[ActionMatcher] = Field(min_length=1)
    scene: TaskScene
    tags: list[Literal["read_screen", "answer_in_memory", "after_failure"]] = Field(
        default_factory=list
    )
    source: Literal["frame", "collected"]
    label_source: Literal["rule", "human"]
    label_note: str
    origin: str
