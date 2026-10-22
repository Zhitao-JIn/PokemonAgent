"""地图交互事件原件。"""

from pydantic import BaseModel

from ....objects import ObjectFactEvent


class ObjectEventsParams(BaseModel):
    events: list[ObjectFactEvent]
