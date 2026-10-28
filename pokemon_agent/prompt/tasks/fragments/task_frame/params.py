"""当前帧与物体事件原料。"""

from pydantic import BaseModel

from ....observation import ObservationRecord


class TaskFrameParams(BaseModel):
    observation: ObservationRecord
