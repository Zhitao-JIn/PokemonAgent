"""Prompt 使用的动作原料，不包含按键帮助或展示签名。"""

from typing import Literal

from pydantic import BaseModel, Field


class ScriptParamRecord(BaseModel):
    name: str
    type: Literal["str", "int"]
    description: str = ""
    default: str | int | None = None


class ActionEntryRecord(BaseModel):
    kind: Literal["key", "script"]
    name: str
    params: list[ScriptParamRecord] = Field(default_factory=list)
    description: str = ""


class ActionSpaceRecord(BaseModel):
    names: list[str]
    scene: str = ""
    mask: dict[str, bool] = Field(default_factory=dict)
    entries: list[ActionEntryRecord] = Field(default_factory=list)
