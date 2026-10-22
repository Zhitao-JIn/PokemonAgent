"""独立的原始观测视图契约。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ObjectFactEventBase(BaseModel):
    class Place(BaseModel):
        map_id: int
        x: int
        y: int

    episode_id: str = Field()
    step: int = Field(ge=0)
    run_id: str = Field(default="")

    class ActorPlace(BaseModel):
        x: int
        y: int

    actor_place: ActorPlace = Field()
    place: Place = Field()
    object_kind: str = Field()
    button: str = Field()


class ObjectDialogEvent(ObjectFactEventBase):
    outcome: Literal["dialog"] = "dialog"
    text: str = Field()


class ObjectWarpEvent(ObjectFactEventBase):
    outcome: Literal["warp"] = "warp"
    map_id: int = Field()


class ObjectStillEvent(ObjectFactEventBase):
    outcome: Literal["still"] = "still"


ObjectFactEvent = Annotated[
    ObjectDialogEvent | ObjectWarpEvent | ObjectStillEvent, Field(discriminator="outcome")
]
