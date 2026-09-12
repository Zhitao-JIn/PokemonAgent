"""从大脑吐出的动作（`ActionFromBrain`）及其连按段（`ActionSegmentFromBrain`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_RATIONALE = 2
"""**一段**动作最多带几条论据。

**从 3 降到 2**：论据的粒度从"整条链"下沉到"段"之后，总量变成"段数 × 条数"，
上限必须跟着收紧（见 `docs/spec/harness/PLAN_action_step_granularity.md` §4b）。
段是单一意图，通常一条依据就够，第二条的位置留给"确实还有一条独立依据"。

抽成常量是因为它有两个执行点——`ActionSegmentFromBrain` 的字段约束（数据契约）
和 `Brain._parse`（外部输入校验）。两处必须同源，否则模型给 3 条时会得到一个
自相矛盾的系统：解析器放行、构造时炸。
"""

MAX_TIMES = 8
"""一段最多连按几次。

**同一个数有两个执行点**——这里的字段约束（数据契约）和 `Brain._parse`
（外部输入校验），所以必须同源，理由同 `MAX_RATIONALE`。

上限存在的理由：模型会写 `"times": "100"`。连按期间 agent 看不见中间状态，
撞墙了也会把剩下几次按完——这是时序抽象的经典取舍，次数是宏动作（机制二）的原始形态。

收益是**省感知调用**：走 5 格从 5 次 VLM 调用变成 1 次。
感知是每步都花钱的那一项，这一下把成本和延迟都砍到五分之一。
"""

MAX_SEGMENTS = 4
"""一条链最多几段。

同一个数有两个执行点——`ActionFromBrain.sequence` 的字段约束和 `Brain._parse`
（外部输入校验），必须同源，理由同上。

上限存在的理由：**段级论据让输出量随段数增长**（段数 × `MAX_RATIONALE`），
而"一次决策按多少个键"直接决定这一圈烧掉多少执行力。不设上限时模型可以写几十段，
一次决策吃光整局的步数预算；中途撞墙时还要把没按的键整段作废。
4 段足够表达"拐几个弯、末尾按一下"。
"""


class ActionSegmentFromBrain(BaseModel):
    """动作链中的一个连续按键段（大脑产、世界执行）。

    **一段 = 一个意图 × 连按次数，论据挂在这一层。**

    `times=4` 这个写法本身就在声明"这 4 下是同一个动作"——所以理由属于段，
    不属于单次按键（为 4 下各写一条理由，等于承认它们该拆成 4 段），
    也不属于整条链（"为什么要交出这串动作"对单个键不成立）。见
    `docs/spec/harness/PLAN_action_step_granularity.md` §4b。
    """

    name: str = Field(min_length=1, description="按键名")
    times: int = Field(default=1, ge=1, le=MAX_TIMES, description=f"连续按键次数，1-{MAX_TIMES}")
    rationale: list[str] = Field(
        min_length=1,
        max_length=MAX_RATIONALE,
        description=f"最能支持**这一段**的论据，1-{MAX_RATIONALE} 条。"
        "进情景记忆；经验能否迁移全看它",
    )


class ActionFromBrain(BaseModel):
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
    活在段上（`ActionSegmentFromBrain.rationale`）——详见该类与
    `docs/spec/harness/PLAN_action_step_granularity.md` §4b。

    **为什么进记忆的是论据而不是结论**：结论（"所以该捡药水"）可以从动作名反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是动作名
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。也正因为它得是"适用条件"，粒度只能是段：
    "地上有药水而我手上没有"支持的是"往右走捡药水"，不是"往右再往上"这个整体计划。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。
    """

    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    sequence: list[ActionSegmentFromBrain] = Field(
        min_length=1,
        max_length=MAX_SEGMENTS,
        description=f"按顺序执行的按键链，1-{MAX_SEGMENTS} 段，每段自带一个论据",
    )

    def segments(self) -> list[ActionSegmentFromBrain]:
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
