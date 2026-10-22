"""当前帧的独立原始观测。"""

from pydantic import BaseModel, Field

from ....objects import ObjectFactEvent
from ....observation import ObservationRecord


class ObservationParams(BaseModel):
    observation: ObservationRecord

    known_objects: list[ObjectFactEvent] = Field(default_factory=list)
