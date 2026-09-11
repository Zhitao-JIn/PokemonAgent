"""追加写的 trace 事件。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

TRACE_SCHEMA_VERSION = 4
"""事件形状的版本号。

**必须有。** 事件形状还会变，而老 JSONL 被新解析器读时不会报错，只会**静默
读错**——少一个字段就当它是空的，多一个就忽略。版本号让「这批数据是旧格式」
变成一句可判断的话。旧格式数据文件（type 值如 `observe`/`think`/`retrieve`…）无法
被当前 `TraceEvent` 解析——不兼容旧格式是明确接受的结果（收敛决策见
`CHANGELOG.md` 2026-09-03 条目）。

v4（0910）：加 `valid` 字段（checkpoint resume 把废弃分支的事件原地打
`valid=false`，不搬不删）；落盘从按局 JSONL 改为一条事件一个 json 文件。
"""


class Source(str, Enum):
    """事件由哪一层产生。

    **每种聚合几乎都要按它切**：感知和决策各烧多少 token、失败集中在哪一层、
    延迟花在哪。放信封不放 payload，就是因为它是横切的。
    """

    PERCEPTION = "perception"  # 视觉模型这条链
    DECISION = "decision"  # 文本模型这条链——只有 think_action 的 choose_once
    HARNESS = "harness"  # 掩码、生命周期、图控制（episode 开始/结束、L2 停摆检测）——
    # 记忆的读/写/蒸馏统一挂 MEMORY，见下。
    WORLD = "world"  # 模拟器
    JUDGE = "judge"  # 成败判定 —— 和决策分开记账，才算得出它自己的准确率。
    VERIFY = "verify"  # step 记忆校验（蒸馏前把关，复用同一个 judge_llm）——
    # 独立于 JUDGE 记账：混在一起时两条链的 token/延迟分不开，
    # 算不出校验器自己的失效率。
    MEMORY = "memory"  # 记忆子系统整体：四类检索（MEMORY_READ）、三类写入
    # （STEP_MEMORY_WRITE/OBJECT_MEMORY_WRITE/EPISODE_MEMORY_WRITE）、跨局摘要蒸馏
    # 这条模型调用（EpisodeMemoryGenerator）。统一挂这里是因为它们都是"记忆子系统
    # 在做什么"，跟决策/判定是不同的关注点——尤其是蒸馏那次模型调用，
    # 一局只烧一次，混进 DECISION 会让"决策平均成本"这个数字失真。
    PLAN = "plan"  # run 级规划器（RunHarness.plan，读目标栈问要不要拆
    # 子目标）——和 episode 内的 DECISION 是两条不同的模型链，独立于
    # HARNESS（那是零成本记账事件的桶），否则"harness 花了多少 token"的
    # 聚合数字失真、也让人以为 harness 是个模型链。


class EventType(str, Enum):
    """trace 事件种类。

    **收敛原则**：type 只回答"这条记录是什么种类"，**与生产者（source）
    正交、数量极小**；原 20 类里"哪个节点/哪类产物"的语义全部降级成
    `payload.kind`（vocabulary 见下方各成员 docstring）。能通过"换一个生产者
    type 不变"测试的只有 `MODEL_CALL`/`ERROR` 两个，其余五个是承认"领域本质
    单源"的产物种类（VIEW 只来自 perception、ACT 的 executed 只来自 world 等）——
    种类名描述的是记录相对世界/模型的位置，不是写它的节点。
    """

    MODEL_CALL = "model_call"
    """一次外部模型交互的**账**（tokens/延迟/attempt/raw）。六条链
    （perception/decision/judge/verify/memory/plan）共用这一个 type，
    区分在 `source` 与 payload。失败时由同一构造器连带补 `ERROR`。
    """
    ERROR = "error"
    """一个失败。所有层共用；`kind` 给失败模式（PermissionSkipped/
    MaxRetriesExceeded/EpisodeSummaryParseFailure…），`source` 给发生在哪条链。
    """
    LLM_OUTCOME = "llm_outcome"
    """一次 LLM 交互后结构化出的**产物**（与 `MODEL_CALL` 配对：账 vs 产物）。
    payload.kind ∈ {intent(think 的意图), verdict(judge 的成败结论),
    audit(verify_steps 的校验汇总)}——三者都是"模型交回内容的再加工"。
    """
    VIEW = "view"
    """世界帧（视觉）的记录。payload.kind ∈ {frame(每步 look 的全量观测),
    after(动作后 look_after 的轻量摘要)}。
    """
    ACT = "act"
    """动作域记录——不限定执行方，因此跨 source：payload.kind ∈ {space
    (get_action_space 允许的动作掩码, source=harness), executed(世界真按了的键,
    source=world), stall(停摆护栏快照, source=harness)}。
    """
    MEMORY_IO = "memory_io"
    """记忆子系统一次读或写。payload.kind ∈ {read_merge(主循环合并读, 全文),
    read_step/read_global/read_knowledge/read_object(四路检索命中摘要),
    read_verify_steps/read_verify_knowledge(收尾校验两读), write_step/
    write_object/write_episode(三类写入)}。
    """
    LIFECYCLE = "lifecycle"
    """流程边界与推进。payload.kind ∈ {run_start/run_end/episode_start/
    episode_end(边界), step(步号推进)}——run/episode 两级边界 + 局内 step 刻度。
    """


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
    type: EventType
    phase: str = Field(
        default="",
        description="循环阶段（observe / retrieve_memory / think / act 等）。"
        "由事件类型推导，和 episode_id + step 一起供观测台聚合。",
    )
    source: Source = Field(description="由哪一层产生。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    frame_png: str | None = Field(
        default=None,
        description="这一步感知到的原始画面，只有 `VIEW` 类事件"
        "（`observe()`/`look_after()` 拼出来的那两种）才会非空——`payload` 保持"
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
        description="这条事件属不属于有效时间线。checkpoint resume 会把游标之后"
        "的废弃分支事件**原地**打 `valid=false`（不搬走不删除——落盘了就不丢，"
        "废弃分支也是审计记录）；读端（rebuild/回放/报表）一律过滤 "
        "`valid=false`，永远只见一条干净时间线，不需要学任何'跳区间'逻辑。"
        "截图便利副本（`screenshot/<event_id>.png`）不参与打标——event_id 永远"
        "递增，resume 重跑零撞名，废弃事件的截图原地保留。",
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)
