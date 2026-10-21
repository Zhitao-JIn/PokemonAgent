"""完整观测片段与记忆快照共用版本化字段投影。"""

from ....interfaces.assembly import Compose
from ..memory_records.params import MemoryParams
from .params import ObservationParams


def assemble(params: ObservationParams, compose: Compose) -> str:
    """完整观测保留当前帧地图，记忆快照仍省略地图。"""
    return compose(
        "memory_records",
        MemoryParams(mode="observation", entries=[], observation=params.observation),
    )
