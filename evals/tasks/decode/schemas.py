"""机械解码的交接契约：同一帧的三个字段组，不把实际输出当作真值。"""

from typing import Any

from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field


class DecodeRun(BaseModel):
    """一次解码全部产物；未加载地图的帧没有地形组。"""

    screen: dict[str, Any] = Field(default_factory=dict)
    takeover: dict[str, Any] = Field(default_factory=dict)
    terrain: dict[str, Any] = Field(default_factory=dict)


class DecodeRecord(StoreModel):
    """solver 写一次，三个 scorer 共读。"""

    run: DecodeRun | None = None
