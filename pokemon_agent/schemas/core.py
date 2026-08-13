"""跨层传递的数据模型。

这里的每个模型都是**接口契约的一部分**：只要出现在 `interfaces/` 的签名里，
它的字段含义就是各层之间的共识，改字段等于改接口。

设计约束（来自 CLAUDE.md 铁律 4）：跨层一律用这里的模型，不用裸 dict。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    summary: str = Field(description="给 LLM 读的自然语言状态描述")
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
    )
    done: bool = Field(default=False, description="episode 是否已终止")


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

    本阶段只有 episodic（这一局发生了什么）。semantic / 值回填留到机制三。
    """

    key: str = Field(description="state abstraction 产出的语义 key，本阶段用 step 占位")
    content: str = Field(description="记忆正文")
    step: int = Field(description="写入时所处的步数")


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
