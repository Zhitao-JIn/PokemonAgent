"""跨层传递的数据模型。

这里的每个模型都是**接口契约的一部分**：只要出现在 `interfaces/` 的签名里，
它的字段含义就是各层之间的共识，改字段等于改接口。

设计约束（来自 CLAUDE.md 铁律 4）：跨层一律用这里的模型，不用裸 dict。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Task(BaseModel):
    """一个有明确成败判据的任务。**episode 的边界就是任务的边界。**

    为什么不用"通关"做 episode：通关是几千步、只产出一个 0/1 结果，
    机制三的蒙特卡洛回填折扣一路乘下去，回填到前期步骤上几乎是噪声；
    评测也只能报"通关了没有"这一个二值数字。任务级则能报成功率、失败模式分布、
    有记忆 vs 无记忆的对比。

    但任务有**下界**：必须长到单靠上下文装不下、必须跨任务复用经验才做得好，
    否则记忆架构就失去了存在理由。"打赢二号道馆"合适，"和 NPC 说句话"不合适。
    """

    task_id: str = Field(description="任务标识，同一任务的多次尝试共用它")
    goal: str = Field(description="给 LLM 读的目标描述，会进 prompt")
    success_criteria: str = Field(description="成败判据的人类可读描述；判定由 world 实现")
    max_steps: int = Field(description="步数上限，超出即判失败。> 0")


class Observation(BaseModel):
    """大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    goal: str = Field(description="当前任务目标。大脑必须知道自己在干嘛，否则无从选择动作")
    summary: str = Field(description="给 LLM 读的自然语言状态描述")
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
    )
    done: bool = Field(default=False, description="episode 是否已终止（成功、失败或超步数）")
    success: bool = Field(
        default=False,
        description="任务是否达成。**只在 done 为 True 时有意义**，否则恒为 False",
    )


class ActionSpace(BaseModel):
    """当前状态下**可用**的动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。
    """

    names: list[str] = Field(description="可用动作名，非空")
    descriptions: dict[str, str] = Field(
        default_factory=dict, description="动作名 -> 给 LLM 读的说明"
    )

    def contains(self, name: str) -> bool:
        return name in self.names


class Action(BaseModel):
    """大脑选出的一个动作。

    `thought` 一起存进来是刻意的：ReAct 的推理过程要进 trace，
    否则 replay 时只知道选了什么、不知道为什么选。
    """

    name: str = Field(description="动作名，必须来自当时的 ActionSpace")
    args: dict[str, str] = Field(default_factory=dict, description="动作参数")
    thought: str = Field(default="", description="选择该动作的推理，仅用于 trace 与调试")


class ToolResult(BaseModel):
    """一次动作执行的结果。"""

    ok: bool = Field(description="是否成功执行。失败不抛异常，因为动作失败是预期内的游戏事件")
    message: str = Field(default="", description="给 LLM 读的结果描述")
    observation: Observation | None = Field(
        default=None, description="执行后的新观测；None 表示调用方需另行 perceive()"
    )


class MemoryEntry(BaseModel):
    """一条记忆。

    本阶段只有 **episodic**：这次任务尝试里发生了什么，是自己跑出来的轨迹。
    作用域 = 一个 episode = 一次任务尝试。

    不要和 **semantic** 混淆：semantic 是**外部领域知识**（"水属性克制火属性"、
    某道馆馆主用什么属性），来自攻略/图鉴，不是自己跑出来的，也不随 episode 结束而失效。
    跨任务复用的成功经验既不是 semantic，也应当先归到 episodic 的聚合，
    或晋升后进 skill library（机制二）。

    semantic 记忆与值回填都留到后面的机制，本阶段不做。
    """

    key: str = Field(description="state abstraction 产出的语义 key，本阶段用 step 占位")
    content: str = Field(description="记忆正文")
    step: int = Field(description="写入时所处的步数")


class EpisodeOutcome(BaseModel):
    """一次任务尝试的最终结果。

    这是评测与机制三的输入：成功率按 task_id 分组统计，
    MC 回填拿 success 作为 episode 的最终回报沿轨迹往回传。
    """

    episode_id: str = Field(description="本次尝试的标识")
    task_id: str = Field(description="尝试的是哪个任务")
    success: bool
    steps: int = Field(description="实际用了多少步")
    reason: str = Field(description="终止原因：success / failed / max_steps_exceeded / error")


class EventType(str, Enum):
    """trace 事件类型。与 CLAUDE.md 第九节的约定一一对应。"""

    OBSERVE = "observe"
    THINK = "think"
    ACT = "act"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    ERROR = "error"
    COST = "cost"


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计四件事的共同底座，
    所以它是**不可变的事件**，不是可变的状态快照——不要往里加"当前状态"这类字段。
    """

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发")
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步")
    type: EventType
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    ts: float = Field(description="Unix 时间戳，秒")
