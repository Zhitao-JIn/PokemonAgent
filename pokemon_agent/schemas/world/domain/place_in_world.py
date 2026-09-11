"""地图上的格子（`PlaceInWorld`）与格子上的东西（`LandmarkInWorld`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .action_semantics import FACING_STEP


class PlaceInWorld(BaseModel):
    """地图上的一个格子。**这是全项目唯一的"位置"表示。**

    做成模型而不是三个散字段，是因为它现在**承载记忆的键**：
    语义记忆按 `(map_id, x, y)` 索引，那三个数必须整体传递、整体比较。
    散着传总有一天会漏掉 `map_id`，而漏掉之后两张地图上的同一个坐标会撞在一起——
    那种错不报错，只会让记忆开始张冠李戴。
    """

    map_id: int
    x: int
    y: int

    def step_toward(self, facing: str) -> PlaceInWorld:
        """面朝 `facing` 时，`a` 会作用到的那一格。"""
        dx, dy = FACING_STEP[facing]
        return PlaceInWorld(map_id=self.map_id, x=self.x + dx, y=self.y + dy)

    @property
    def key(self) -> str:
        """记忆的键。**跨 episode 稳定**——同一张地图上的同一格永远是同一个键。"""
        return f"{self.map_id}:{self.x}:{self.y}"

    def render(self) -> str:
        """渲染成进 prompt 的样子。"""
        """**全局坐标写成 `x= y=`，不用括号** —— 括号写法留给屏幕格。"""
        return f"全局坐标 地图{self.map_id} x={self.x} y={self.y}"


class LandmarkInWorld(BaseModel):
    """世界里格子上的一个东西：门 / 招牌 / 人。类型和位置都来自模拟器内存。

    **没有名字。** 名字在总览画面里没有可观测的证据，只能靠走过去交互再记住——
    那正是语义记忆（object）的活。
    """

    kind: str = Field(description="门 / 招牌 / 人")
    place: PlaceInWorld

    def render(self) -> str:
        """渲染成 prompt 里那一行。"""
        return f"{self.kind} x={self.place.x} y={self.place.y}"


KIND_DOOR, KIND_SIGN, KIND_PERSON = "门", "招牌", "人"
"""地标的三种类型。**下半部分那组 `DOOR/SIGN/PERSON` 是地图上的字符 `D/S/N`，
不是这个**——两组名字撞过一次，症状是门的分支静默不生效。"""
