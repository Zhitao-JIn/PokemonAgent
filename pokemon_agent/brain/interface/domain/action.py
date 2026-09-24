"""从大脑吐出的动作（`Action`）及其连按段（`ActionSegment`）。

**这里没有任何上限常量。** "最多几段 / 每段最多按几次 / 每段最多几条论据"
是**调用方的校验策略**（tool/harness 决定），不是大脑对自己产物的承诺——
大脑只保证"形状对"（键名字符串、次数正整数、论据非空）。上限写在这里会
把校验固化成两处（字段约束一处、调用方一处），一旦不同步就会出现
"解析器放行、构造时炸"的自相矛盾系统。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActionSegment(BaseModel):
    """动作链中的一个连续按键段（大脑产、世界执行）。

    **一段 = 一个意图 × 连按次数。**

    `times=4` 这个写法本身就在声明"这 4 下是同一个动作"。（0923 189 起
    段上不再带论据——JEV 不产出 rationale，字段连同输出契约一起删了；
    0924 起链级的 `thought` 也删了，见 `Action`。）
    """

    name: str = Field(min_length=1, description="按键名")
    times: int = Field(default=1, ge=1, description="连续按键次数")


class Action(BaseModel):
    """**从大脑吐出的动作**，交给世界执行。

    只有一样东西：`sequence`，给世界执行的按序按键链（每段 = 一个键 × 连按次数）。
    **这一版只有按键一类动作**：`intent` 分派（press / push_goal）连同它的
    枚举一起删了，拆子目标的机制会在别处重写。

    **没有推理字段**：决策是每键一次的快速响应，"为什么这么做"归 task 的拆解
    （`Decomposition` 的 `why`），不归选键。经验记忆里因此只有
    "看到什么 → 做了什么 → 变成什么"，适用条件的判断交给读记忆的人。

    **本类不校验上限**（段数上限、次数上限）——那是调用方的
    校验策略，见本模块 docstring。
    """

    sequence: list[ActionSegment] = Field(
        min_length=1,
        description="按顺序执行的按键链",
    )

    def segments(self) -> list[ActionSegment]:
        """返回规范化后的动作链。"""
        return list(self.sequence)

    def describe(self) -> str:
        """返回适合写入 trace 和记忆的动作链文本。

        `times == 1` 的段省掉 `×1` 后缀——执行粒度下沉到单键之后，绝大多数
        `describe()` 的结果就是 `up`，带上 `×1` 只会让每条记忆都多两个字符。
        """
        parts = [
            f"{seg.name}×{seg.times}" if seg.times > 1 else seg.name for seg in self.segments()
        ]
        return " -> ".join(parts)
