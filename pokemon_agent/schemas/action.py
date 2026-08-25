"""动作契约：大脑能做什么、选出来的一步长什么样。**跨层**——出现在
`GameToolPort`/`BrainPort` 的签名里。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .observation import Observation


class Intent(str, Enum):
    """大脑这一轮想做哪一类事。**它是图的分派依据。**

    分成三类而不是把它们都塞进按键里，是因为它们**代价和后果完全不同**：
    只有 `PRESS` 推进世界（不可逆），另外两类只改变大脑自己的处境。
    分开之后"它花了多少轮在想、多少轮在走"是可以直接从 trace 数出来的。

    往里加第四类（读记忆、写记忆、调工具）时，加的是一个枚举值加一个图节点，
    `choose()` 和 prompt 的形状不变——这是把它做成枚举而不是布尔标志的收益。
    """

    PRESS = "press"
    """按键，推进世界。**唯一不可逆的一类。**"""

    PUSH_GOAL = "push_goal"
    """把当前目标拆出一个更近的子目标压进栈。不推进世界。"""


class Goal(BaseModel):
    """一个目标：想达成什么，以及**怎么算达成**。

    两样一起给，不能只给前者：判定器的输入就是这两项，没有判据它无从判断，
    只能凭"看起来差不多了"回答——而那正是成功率会被污染的地方。

    所以大脑压子目标时必须同时写出判据。写不出判据的子目标，
    本身就说明它没想清楚要什么。
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

    - `name` / `args` —— 给世界执行。
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

    intent: Intent = Field(
        default=Intent.PRESS,
        description="这一轮做哪一类事。**分派靠它**，`name` 只在 PRESS 时有意义",
    )
    name: str = Field(
        default="", description="按键名，必须来自当时的 ActionSpace。只在 PRESS 时有意义"
    )
    args: dict[str, str] = Field(
        default_factory=dict, description="按键参数，目前只有 `times`（连按几次）"
    )
    goal: Goal | None = Field(
        default=None, description="要压进目标栈的子目标。只在 PUSH_GOAL 时有意义"
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

    @model_validator(mode="after")
    def _fields_must_match_the_intent(self) -> Action:
        """每种 intent 的必填字段不同，**在这里挡住**，不要漏到分派的时候。

        漏过去的话，`push_goal` 少了 `goal` 会在 Harness 里 assert 崩掉——
        那是把**模型的输出问题**报成了**我们自己的契约违约**，看堆栈会指错方向。
        在这里失败则走 `ParseFailure`，会被重试，也会按失败模式统计。
        """
        if self.intent is Intent.PRESS and not self.name:
            raise ValueError("intent=press 必须给 action（按键名）")
        if self.intent is Intent.PUSH_GOAL and self.goal is None:
            raise ValueError("intent=push_goal 必须给 goal 和 criteria")
        return self


class ActionSpace(BaseModel):
    """当前状态下**可用**的动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。
    """

    intents: list[Intent] = Field(
        default_factory=lambda: [Intent.PRESS],
        description="这一轮允许哪几类动作。**由 Harness 填**——"
        "能不能拆子目标取决于栈有多深，那是循环的事，工具层不知道",
    )
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
