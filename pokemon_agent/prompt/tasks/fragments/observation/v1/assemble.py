"""完整观测片段与记忆快照共用版本化字段投影。"""

from ....interfaces.assembly import Compose
from ..memory_records.params import MemoryParams
from ..object_events.params import ObjectEventsParams
from .params import ObservationParams


def assemble(params: ObservationParams, compose: Compose) -> str:
    """完整观测保留当前帧地图，记忆快照仍省略地图。"""
    observation = params.observation
    if params.known_objects:
        text = compose("object_events", ObjectEventsParams(events=params.known_objects))
        observation = observation.model_copy(
            update={"facts": observation.facts.model_copy(update={"known_objects": text})}
        )
    return compose(
        "memory_records",
        MemoryParams(mode="observation", entries=[], observation=observation),
    )
