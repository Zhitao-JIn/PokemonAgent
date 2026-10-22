"""当前帧与物体事件原料。"""

from pydantic import BaseModel, Field

from ....objects import ObjectFactEvent
from ....observation import ObservationRecord


class TaskFrameParams(BaseModel):
    observation: ObservationRecord
    known_objects: list[ObjectFactEvent] = Field(default_factory=list)
