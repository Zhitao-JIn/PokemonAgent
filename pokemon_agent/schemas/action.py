"""动作契约：大脑能做什么、选出来的一步长什么样。**跨层**——出现在
`GameToolPort`/`BrainPort` 的签名里。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .observation import Observation


class Goal(BaseModel):
    """一个目标：想达成什么，以及**怎么算达成**。

    两样一起给，不能只给前者：判定器的输入就是这两项，没有判据它无从判断，
    只能凭"看起来差不多了"回答——而那正是成功率会被污染的地方。

    本阶段一局只有一个目标，由任务给定（`goals` 栈里恒为一层，见
    `harness.LoopState.goals`）。目标栈这个形状留着，是因为拆子目标要回来——
    但**拆的机制会在别处重写**，不是现在这个 intent 分派。
    """

    goal: str = Field(min_length=1, description="想达成什么，一句话")
    criteria: str = Field(
        min_length=1, description="画面上出现什么才算达成。**要能只看一帧就判断**"
    )


MAX_RATIONALE = 3
"""一个动作最多带几条论据。

抽成常量是因为它有两个执行点——`Action` 的字段约束（数据契约）和 `Brain._parse`
（外部输入校验）。两处必须同源，否则模型给 4 条时会得到一个自相矛盾的系统：
解析器放行、构造时炸。
"""


class Action(BaseModel):
    """大脑选出的一个动作。

    它带着三样东西过来，服务于三个不同的消费方，**不要合并**：

    - `name` / `args` —— 给世界执行。**这一版只有按键一类动作**：
      `intent` 分派（press / push_goal）连同它的枚举一起删了，
      拆子目标的机制会在别处重写。
    - `thought` —— 完整推理，**只进 trace**，不参与任何后续决策。
      不设长度上限：它的长度就是模型这一步的算力，压缩它压的是思考本身，
      不是日志体积。
    - `rationale` —— 最能支持这个动作的论据，**进情景记忆**，会被未来的步骤检索回去。

    为什么进记忆的是论据而不是结论：结论（"所以该捡药水"）可以从 `name` 反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是 `name`
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。
    """

    name: str = Field(
        min_length=1, description="按键名，必须来自当时的 ActionSpace"
    )
    args: dict[str, str] = Field(
        default_factory=dict, description="按键参数，目前只有 `times`（连按几次）"
    )
    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    rationale: list[str] = Field(
        min_length=1,
        max_length=MAX_RATIONALE,
        description=f"最能支持该动作的论据，1-{MAX_RATIONALE} 条。"
        "进情景记忆；经验能否迁移全看它",
    )


class ActionSpace(BaseModel):
    """当前状态下**可用**的动作集合（state-dependent action masking）。

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

    def contains(self, name: str) -> bool:
        return name in self.names


class ToolResult(BaseModel):
    """一次动作执行的结果。

    ## 这里曾经有一个 `ok`

    含义是"这个动作有没有产生预期效果"（撞墙 = False）。在 `PyBoyWorld` 上它被
    写死成 `True`，因为从像素判断"这一下有没有改变世界"没有便宜可靠的办法——
    画面本身就有动画，比对不出因果。

    **一个恒为真的布尔值比没有更糟**：它出现在事件流里、出现在控制台的判断分支里，
    让人以为那里有信息，而实际上每一条都是 True。

    要让它诚实，唯一的办法是读内存里的坐标（走没走动）——但那是为一个**没有消费方**
    的字段新增一处内存依赖。判断动作有没有生效，本来就该由**前后两次观察的对比**
    来回答，而那件事情景记忆层已经在做了（`MemoryEntry` 两头各存一份完整快照）。

    所以删掉，不是补上。
    """

    message: str = Field(default="", description="给 LLM 读的结果描述")
    observation: Observation | None = Field(
        default=None, description="执行后的新观测；None 表示调用方需另行 perceive()"
    )
    calls: list[dict[str, str]] = Field(
        default_factory=list,
        description="推进这一步过程中产生的模型调用记录（通常是执行后重新感知那一次）。"
        "语义同 `PerceptionResult.calls`：按序排列、失败的也算数、"
        "空列表表示命中缓存没有新调用，**不是 None**。放在这里而不是单独一个"
        "`drain_calls()`——calls 就是这次 `execute()` 顺带产出的东西，"
        "没有理由靠额外一次取账把它和结果分开传",
    )
