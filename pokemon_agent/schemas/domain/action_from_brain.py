"""从大脑吐出的动作（`ActionFromBrain`）及其连按段（`ActionSegmentFromBrain`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import MAX_RATIONALE, MAX_TIMES


class ActionSegmentFromBrain(BaseModel):
    """动作链中的一个连续按键段（大脑产、世界执行）。"""

    name: str = Field(min_length=1, description="按键名")
    times: int = Field(default=1, ge=1, le=MAX_TIMES, description=f"连续按键次数，1-{MAX_TIMES}")


class ActionFromBrain(BaseModel):
    """**从大脑吐出的动作**，交给世界执行。

    它带着三样东西过来，服务于三个不同的消费方，**不要合并**：

    - `sequence` —— 给世界执行。按序的按键链（每段 = 一个键 × 连按次数）；
      **这一版只有按键一类动作**：`intent` 分派（press / push_goal）连同它的
      枚举一起删了，拆子目标的机制会在别处重写。
    - `thought` —— 完整推理，**只进 trace**，不参与任何后续决策。
      不设长度上限：它的长度就是模型这一步的算力，压缩它压的是思考本身，
      不是日志体积。
    - `rationale` —— 最能支持这个动作的论据，**进情景记忆**，会被未来的步骤检索回去。

    为什么进记忆的是论据而不是结论：结论（"所以该捡药水"）可以从动作名反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是动作名
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。
    """

    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    rationale: list[str] = Field(
        min_length=1,
        max_length=MAX_RATIONALE,
        description=f"最能支持该动作的论据，1-{MAX_RATIONALE} 条。进情景记忆；经验能否迁移全看它",
    )
    sequence: list[ActionSegmentFromBrain] = Field(description="按顺序执行的按键链，非空")

    def segments(self) -> list[ActionSegmentFromBrain]:
        """返回规范化后的动作链。"""
        return list(self.sequence)

    def describe(self) -> str:
        """返回适合写入 trace 和记忆的动作链文本。"""
        return " -> ".join(f"{segment.name}×{segment.times}" for segment in self.segments())
