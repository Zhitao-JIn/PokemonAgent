"""Trace 契约：记账、判定结果、事件流。**跨层**——`ModelCall`/`Decision`/`Verdict`
出现在 `BrainPort` 的签名里，`TraceEvent` 出现在 `TracePort` 的签名里。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .action import Action


class ModelCall(BaseModel):
    """一次模型调用留下的账，外加它成没成。

    ## 为什么大脑要把账"交出来"而不是自己记

    **只有 Harness 写 trace。** 大脑是被调用方：它返回结果和账单，
    由 Harness 翻译成事件。上一版不是这样——brain 自己写 MODEL_CALL / THINK /
    ERROR / MEMORY_READ，harness 写 ACT / MEMORY_WRITE / OBSERVE / EPISODE_*，
    于是"某类事件归谁写"要一条条记，还开了个例外（judge 不写 trace，为的是让
    判定器碰不到自己的账）——用例外弥补一条不统一的规则。

    统一之后规则只有一句：**谁控制循环，谁记账。** 判定器碰不到自己的账
    也就不再是特权设计，而是所有大脑调用的共同处境。

    `payload` 直接就是 trace 里 `MODEL_CALL` 的内容。`error_kind` 非空时
    Harness 会**另外补一条 `ERROR` 事件**——账单和失败模式是两件事：
    前者回答"花了多少钱"，后者回答"为什么没拿到东西"，混在一条里两个都统计不出来。
    """

    payload: dict[str, str] = Field(
        default_factory=dict,
        description="token、延迟、prompt 版本、第几次尝试、原始输出。**失败的调用也要有**——"
        "它同样烧了钱，而 `raw` 让你改进解析器之后能离线重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")


class Decision(BaseModel):
    """大脑选一次动作的**全部产物**：动作、账单、它翻过哪些记忆。

    `action` 为 None 表示重试全部用尽——**这不是异常，是一类要被统计的失败模式**。
    抛异常的是 Harness（它才知道这一局的死活），大脑只如实汇报。
    """

    action: Action | None = Field(
        default=None, description="选中的动作；None = 重试用尽，一次都没解析出合法动作"
    )
    calls: list[ModelCall] = Field(
        default_factory=list, description="每一次尝试一条，成功失败都在里面，按发生顺序"
    )
    recalled: list[str] = Field(
        default_factory=list,
        description="取回了哪几条情景记忆，形如 `(episode_id, step)`。"
        "**记引用而不只是条数**——只记数量的话，replay 时无法回答"
        "「这个决策是被哪条经验影响的」，而那正是「记忆到底有没有用」要查的东西",
    )


class Verdict(BaseModel):
    """一次成败判定的结果，连同它花了什么。

    跨层了才做成模型：大脑产出它，Harness 读 `done` 决定要不要终止、
    把 `call` 写进 trace。两边对这三个字段的期待必须是同一份契约。
    """

    done: bool = Field(description="任务达成了没有。**拿不准一律 False**")
    why: str = Field(
        description="看到了什么证据（或为什么证据不足）。"
        "每一个 True 都得说得出依据，否则成功率就是一个无法证伪的数字"
    )
    call: ModelCall = Field(
        default_factory=lambda: ModelCall(),
        description="这次判定的账。判定和决策各自烧 token，分不开就说不清"
        "「成功率这个数字本身花了多少钱」，也算不出判定器自己的失效率——"
        "而**没有失效率的判定器等于没有判定器**",
    )


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


TRACE_SCHEMA_VERSION = 2
"""事件形状的版本号。

**必须有。** 事件形状还会变（这一版就是第二版），而老 JSONL 被新解析器读时
不会报错，只会**静默读错**——少一个字段就当它是空的，多一个就忽略。
版本号让「这批数据是旧格式」变成一句可判断的话。
"""


class Source(str, Enum):
    """事件由哪一层产生。

    **每种聚合几乎都要按它切**：感知和决策各烧多少 token、失败集中在哪一层、
    延迟花在哪。放信封不放 payload，就是因为它是横切的。
    """

    PERCEPTION = "perception"   # 视觉模型这条链
    DECISION = "decision"       # 文本模型这条链
    HARNESS = "harness"         # 掩码、记忆、生命周期
    WORLD = "world"             # 模拟器
    JUDGE = "judge"             # 成败判定 —— 和决策分开记账，才算得出它自己的准确率
    MEMORY = "memory"           # 跨局摘要记忆生成（EpisodeMemoryGenerator）——
    # 和 DECISION 分开记账：这条链的 token 花费不发生在 ReAct 循环里，
    # 一局只烧一次，混进 DECISION 会让"决策平均成本"这个数字失真。


class EventType(str, Enum):
    """trace 事件类型。"""

    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    OBSERVE = "observe"
    MODEL_CALL = "model_call"
    THINK = "think"
    ACT = "act"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    OBJECT_NOTE = "object_note"
    """记下了「某一格的东西给了什么」（语义记忆 · object）。**和 MEMORY_WRITE 分开**：

    它们是两种记忆（一次经过 vs 那一格本身），寿命和用途都不同。
    混成一类就数不出"它认识了多少个东西"——而那正是语义记忆有没有用的直接指标。
    """
    INSPECT = "inspect"
    """细看了一次。**和 OBSERVE 分开**：它是大脑主动要的，不是每步必发的那一帧。

    混在一起就算不出「它多久要细看一次」，而那正是判断这个动作值不值那次钱的依据。
    """
    GOAL_POP = "goal_pop"
    """一层目标判为完成、出栈。

    `GOAL_PUSH` 和它是一对，**这一版删掉了**：拆子目标的 intent 分派没有了，
    没有任何东西会压栈，一个零生产者的事件类型只会让统计脚本里多一个恒为 0 的桶。
    拆解机制在别处重写时它跟着回来——那时"它拆了几层"和"它完成了几层"仍然是
    两个必须分开数的数，所以届时仍然是两个类型，不是一个带方向的字段。
    """
    ERROR = "error"
    CHECKPOINT = "checkpoint"
    EPISODE_MEMORY_WRITE = "episode_memory_write"
    """写入一条跨局摘要记忆（`EpisodeMemory`，见 `schemas/episode_memory.py`）。

    **和 `MEMORY_WRITE` 分开**：那是单步记忆，一局内产生也可能一局内被读回；
    这条是一局结束后蒸馏出的摘要，跨局存在、跨局检索。混成一类，
    "一局到底攒了几条经验 vs 沉淀出几条可复用摘要"这两个数就分不出来了。
    """


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因
    的共同底座，所以它是**不可变的事件**，不是可变的状态快照——
    不要往里加"当前状态"这类字段，那样就没法重放了。
    """

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(
        description="哪一次实验。**manifest 的 join key**——"
        "没有它，一份记着模型与 prompt 的 manifest 和一堆事件对不上"
    )
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: EventType
    phase: str = Field(
        default="",
        description="循环阶段（observe / retrieve_memory / think / act 等）。"
        "由事件类型推导，和 episode_id + step 一起供观测台聚合。",
    )
    source: Source = Field(description="由哪一层产生。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    ts: float = Field(
        description="Unix 时间戳，秒。用于算延迟与对齐外部日志；"
        "**不能替代 event_id 排序**——同毫秒多条事件、时钟回拨都会让时间序失真"
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)
