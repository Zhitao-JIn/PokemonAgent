"""地图上的格子（`PlaceInWorld`）。**这是全项目唯一的"位置"表示。**

`LandmarkInWorld`（格子上的东西）与它的 `KIND_*` 常量原来在这个文件，搬到了
`world/interface/domain/facts.py`，变成 `Facts.Landmark`（内部类，`KIND_*`
常量变成它的 `ClassVar`）——那是"世界事实"这个概念的一部分，跟 `PlaceInWorld`
（放之四海皆准的坐标表示，`Facts` 之外也大量被引用）不是同一层次的东西。
"""

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
