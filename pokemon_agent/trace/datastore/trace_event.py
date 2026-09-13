"""追加写的 trace 事件。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TRACE_SCHEMA_VERSION = 4
"""事件形状的版本号。

**必须有。** 事件形状还会变，而老 JSONL 被新解析器读时不会报错，只会**静默
读错**——少一个字段就当它是空的，多一个就忽略。版本号让「这批数据是旧格式」
变成一句可判断的话。旧格式数据文件（type 值如 `observe`/`think`/`retrieve`…）无法
被当前 `TraceEvent` 解析——不兼容旧格式是明确接受的结果（收敛决策见
`CHANGELOG.md` 2026-09-03 条目）。

v4（0910）：加 `valid` 字段（当时 checkpoint resume 会把废弃分支的事件原地打
`valid=false`，不搬不删；恢复链已删，字段留作历史数据兼容）；落盘从按局
JSONL 改为一条事件一个 json 文件。
"""


class Source:
    """事件由哪一层产生。**是字符串常量，不是枚举**（0913 降级）。

    理由：trace 不可能只服务这一个项目，它的契约只有"按时间记账"。
    磁盘上一直是裸字符串（`"source": "plan"`），前端读的也是字面量——
    枚举只是内存里一层没人认的包装。

    取值见 `SourceName`。
    """

    PERCEPTION = "perception"  # 视觉模型这条链
    DECISION = "decision"  # 文本模型这条链——只有 think_action 的 choose
    HARNESS = "harness"  # 掩码、生命周期、图控制（episode 开始/结束、L2 停摆检测）
    WORLD = "world"  # 模拟器
    JUDGE = "judge"  # 成败判定 —— 和决策分开记账，才算得出它自己的准确率。
    VERIFY = "verify"  # step 记忆校验（蒸馏前把关，复用同一个 judge_llm）
    MEMORY = "memory"  # 记忆子系统整体：四类检索、三类写入、跨局摘要蒸馏这条模型调用
    PLAN = "plan"  # run 级规划器（RunHarness.plan）


SourceName = Literal[
    "perception", "decision", "harness", "world", "judge", "verify", "memory", "plan",
]
"""`Source` 的合法值域（**类型级表达只有这一处**）。

"每种聚合几乎都要按 source 切"这条需求不变：感知和决策各烧多少 token、
失败集中在哪一层、延迟花在哪。放信封不放 payload，就是因为它是横切的。
"""


class EventType:
    """trace 事件种类。**是字符串常量，不是枚举**（0913 降级）。

    **收敛原则**：type 只回答"这条记录是什么种类"，**与生产者（source）
    正交、数量极小**；原 20 类里"哪个节点/哪类产物"的语义全部降级成
    `payload.kind`。能通过"换一个生产者 type 不变"测试的只有 `MODEL_CALL`/
    `ERROR` 两个，其余五个是承认"领域本质单源"的产物种类（VIEW 只来自
    perception、ACT 的 executed 只来自 world 等）——种类名描述的是记录相对
    世界/模型的位置，不是写它的节点。

    取值见 `EventTypeName`。
    """

    MODEL_CALL = "model_call"  # 一次外部模型交互的账（六条链共用，区分在 source）
    ERROR = "error"  # 一个失败（所有层共用，kind 给失败模式，source 给哪条链）
    LLM_OUTCOME = "llm_outcome"  # 一次 LLM 交互后结构化出的产物（与 MODEL_CALL 配对）
    VIEW = "view"  # 世界帧（视觉）的记录：kind ∈ {frame, after}
    ACT = "act"  # 动作域记录：kind ∈ {space, executed, stall, truncated}
    MEMORY_IO = "memory_io"  # 记忆子系统一次读或写
    LIFECYCLE = "lifecycle"  # 流程边界与推进（run/episode 边界 + 局内 step 刻度）


EventTypeName = Literal[
    "model_call", "error", "llm_outcome", "view", "act", "memory_io", "lifecycle",
]
"""`EventType` 的合法值域（**类型级表达只有这一处**）。"""


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因
    的共同底座，所以它是**不可变的事件**，不是可变的状态快照——
    不要往里加"当前状态"这类字段，那样就没法重放了。
    """

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")
    # 0907：`frame_png` 从 `bytes` 改为 base64 `str`——JSONL 落盘本来就是
    # base64（pydantic 对 bytes 自动编码，磁盘格式不变），但 python 模式的
    # `model_dump()` 会原样吐 bytes，凡是把事件直接塞进 HTTP 响应的路径
    # （`GET /runs/{id}/review` 带完整 episode_trace）都会在 JSON 序列化时
    # 炸"invalid utf-8"。改成 str 后内存/磁盘/HTTP 三处形态统一，
    # 也跟 `StepMemory.before_frame`/`VisionDescribeReq.images` 同一约定。

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(
        description="哪一次实验。**manifest 的 join key**——"
        "没有它，一份记着模型与 prompt 的 manifest 和一堆事件对不上"
    )
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: str = Field(description="事件种类（见 `EventType` 的常量；空字符串的实现在这里不存在）")
    phase: str = Field(
        default="",
        description="循环阶段（observe / retrieve_memory / think / act 等）。"
        "由事件类型推导，和 episode_id + step 一起供观测台聚合。",
    )
    source: str = Field(description="由哪一层产生（见 `Source` 的常量）。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    frame_png: str | None = Field(
        default=None,
        description="这一步感知到的原始画面，只有 `VIEW` 类事件"
        "（`observe()`/`after_action()` 拼出来的那两种）才会非空——`payload` 保持"
        "`dict[str, str]` 纯文本不变，二进制单独开一个字段，JSONL 其余内容"
        "仍然是人可以直接读的文本。`None` = 这条事件没有对应的落盘帧"
        "（非视觉世界、或这条根本不是感知事件）。",
    )
    ts: float = Field(
        description="Unix 时间戳，秒。用于算延迟与对齐外部日志；"
        "**不能替代 event_id 排序**——同毫秒多条事件、时钟回拨都会让时间序失真"
    )
    valid: bool = Field(
        default=True,
        description="这条事件属不属于有效时间线。**新写入的事件恒为 `true`**——本"
        "仓已无 checkpoint 恢复（打标能力随恢复链一并删除，见 `CHANGELOG.md`）；"
        "字段保留是为了兼容历史落盘数据（0910–0913 期间 resume 会把游标之后的废弃"
        "分支原地打 `valid=false`），读端一律过滤 `valid=false`，永远只见一条干净"
        "时间线。",
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)
