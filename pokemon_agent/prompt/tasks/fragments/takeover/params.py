"""场合业务视图的封闭联合。"""

from pydantic import BaseModel

from ....observation import TakeoverView


class TakeoverParams(BaseModel):
    view: TakeoverView
