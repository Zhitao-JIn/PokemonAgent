"""喂给大脑的可用动作集合（给大脑看的"此刻能按什么"）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActionSpace(BaseModel):
    """**喂给大脑的**当前可用动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。
    """

    names: list[str] = Field(description="可用按键名，非空")
    descriptions: dict[str, str] = Field(
        default_factory=dict, description="动作名 -> 给 LLM 读的说明"
    )
    note: str = Field(
        default="",
        description="关于整个动作空间的说明（如连按怎么用），不属于任何单个动作。"
        "**必须有这个字段**：prompt 只渲染 names 里的动作说明，"
        "塞进 descriptions 的额外条目永远不会被渲染出去",
    )
    map_note: str = Field(
        default="",
        description="怎么读地图/判断证据的说明（`MAP_HINT`）。"
        "跟 `note`（连按怎么用）分开存是有意的：两者在 prompt 里渲染到不同位置——"
        "`map_note` 紧跟在已知事实之后（判断证据这类规则要在模型看到 facts 后立刻读到，"
        "不能等到读完一大段按键说明才看到），`note` 留在可用按键那一节——"
        "地图/证据规则挂在'可用按键'标题下面会位置和内容对不上。",
    )

    def contains(self, name: str) -> bool:
        """这个按键在不在当前动作空间里。"""
        return name in self.names
