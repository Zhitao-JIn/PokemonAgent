"""当前帧的独立原始观测。"""

from pydantic import BaseModel

from ....observation import ObservationRecord


class ObservationParams(BaseModel):
    observation: ObservationRecord
