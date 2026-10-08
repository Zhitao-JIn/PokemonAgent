"""喂给大脑的可用动作集合（给大脑看的"此刻能按什么"）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .action_entry import ActionEntry


class ActionSpace(BaseModel):
    """**喂给大脑的**当前可用动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。

    **统一能力掩码**：`mask` 是 `名字 → 是否可用` 的**扁平命名空间**，原子键与
    脚本混在一起——调用方（模型）只做一次选择：名字 ∈ 掩码且 enabled；`entries`
    只带各自的载荷差异（脚本有参数与说明，键只有一个名字）。`names` 旧字段保留给
    prompt 渲染按键说明用，与 `mask` 一致性由 `compute_action_space()` 一处产出保证。
    """

    scene: str = Field(default="", description="这份掩码是按哪个场合算的（可追溯）")
    mask: dict[str, bool] = Field(
        default_factory=dict, description="名字 → 此刻是否可用（键与脚本同一命名空间）"
    )
    entries: list[ActionEntry] = Field(
        default_factory=list, description="掩码里各条目的载荷（参数签名、说明）"
    )

    names: list[str] = Field(description="可用按键名；仅开放脚本的场合为空（只给脚本）")
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

    def enabled(self, name: str) -> bool:
        """这个名字此刻是否可用（统一掩码的唯一判据，键与脚本同一条规则）。"""
        return self.mask.get(name, False)

    def entry(self, name: str) -> ActionEntry | None:
        """按名字取条目载荷；掩码里没有则为 None。"""
        return next((e for e in self.entries if e.name == name), None)
