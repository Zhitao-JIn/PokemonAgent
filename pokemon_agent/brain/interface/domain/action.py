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

    **一段 = 一个意图 × 连按次数，论据挂在这一层。**

    `times=4` 这个写法本身就在声明"这 4 下是同一个动作"——所以理由属于段，
    不属于单次按键（为 4 下各写一条理由，等于承认它们该拆成 4 段），
    也不属于整条链（"为什么要交出这串动作"对单个键不成立）。见
    `docs/spec/harness/PLAN_action_step_granularity.md` §4b。
    """

    name: str = Field(min_length=1, description="按键名")
    times: int = Field(default=1, ge=1, description="连续按键次数")
    rationale: list[str] = Field(
        min_length=1,
        description="最能支持**这一段**的论据。"
        "进情景记忆；经验能否迁移全看它",
    )


class Action(BaseModel):
    """**从大脑吐出的动作**，交给世界执行。

    它带着两样东西过来，服务于两个不同的消费方，**不要合并**：

    - `sequence` —— 给世界执行。按序的按键链（每段 = 一个键 × 连按次数 + 这一段的论据）；
      **这一版只有按键一类动作**：`intent` 分派（press / push_goal）连同它的
      枚举一起删了，拆子目标的机制会在别处重写。
    - `thought` —— 完整推理，**只进 trace**，不参与任何后续决策。
      不设长度上限：它的长度就是模型这一步的算力，压缩它压的是思考本身，
      不是日志体积。

    **链上没有论据，这是有意的。** "为什么要交出这串动作"是链级的，对其中任何
    单个键都不成立，所以它由 `thought` 承担（本来就只进 trace）；进记忆的论据
    活在段上（`ActionSegment.rationale`）——详见该类与
    `docs/spec/harness/PLAN_action_step_granularity.md` §4b。

    **为什么进记忆的是论据而不是结论**：结论（"所以该捡药水"）可以从动作名反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是动作名
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。也正因为它得是"适用条件"，粒度只能是段：
    "地上有药水而我手上没有"支持的是"往右走捡药水"，不是"往右再往上"这个整体计划。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。

    **本类不校验上限**（段数上限、次数上限、论据条数上限）——那是调用方的
    校验策略，见本模块 docstring。
    """

    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    sequence: list[ActionSegment] = Field(
        min_length=1,
        description="按顺序执行的按键链，每段自带一个论据",
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
