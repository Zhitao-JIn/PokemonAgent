"""harness → `TraceTool` 的记账请求协议：`FromHarnessToTraceToolAppendReq`。

harness 只负责组装——从这一步手头的领域对象里挑出本笔账需要的字段、声明
`kind`；tool 对 req 做处理（按 kind 渲染 payload、必要时一拆多），模块
（`TracePort` 的实现）只收渲染好的五元组。

**按 `kind` 分派、不按领域对象类型分派**：同一个类型产出不同事件——
`ModelCall` 可以是决策账单（attempt）/判定账单（depth+why）/校验账单
（verdicts），`StepMemory` 有读（一批）有写（单条）；类型名决定不了格式，
"这是哪笔账"只有调用方知道。

各 kind 必填的字段见 `tools/trace/render.py` 每个渲染函数入口的 assert；
payload 字段格式是跨模块契约（观测台前端按字段名渲染），变更权在 tool 层。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.brain.interface import (
    Action,
    ActionSegment,
    Goal,
    StepVerifyVerdict,
    Task,
)
from pokemon_agent.providers.interface import ModelCall
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, StepMemory
from pokemon_agent.trace import Source
from pokemon_agent.world import Observation
from pokemon_agent.trace.interface import TraceKind

from .FromRunHarnessToEpisodeHarnessRunResp import FromRunHarnessToEpisodeHarnessRunResp
from .RunResp import RunResp


class FromHarnessToTraceToolAppendReq(BaseModel):
    """一笔 trace 账的组装结果：公共字段 + 按 kind 取用的领域对象。

    公共字段：`episode_id`/`step`（run 级账沿用项目约定——episode_id 位放
    `run_id`、step 恒 0）与 `kind`；其余字段全部可选，按 kind 取用，
    多余字段留着无妨（渲染函数只读自己那几个）。

    `error`：异常的字符串快照（`f"{type(exc).__name__}: {exc}"`），由调用方
    组装——Exception 对象进不了 Pydantic 模型，也没必要进。
    """

    episode_id: str
    step: int
    kind: TraceKind

    # ---- 通用账目字段 ----
    source: Source | None = None
    call: ModelCall | None = None
    attempt: int | None = None
    why: str | None = None
    depth: int | None = None
    error: str | None = None
    frame_png: str | None = None
    # screenshot_step 已随 0910 截图重构删除：截图文件名 = 承载 frame_png 的
    # 那条事件自己的 event_id（永远递增零撞名），不再按 step 号命名；
    # "这张图是第几步的开局画面"由调用方自己在 harness 侧记 event_id 对账。

    # ---- 边界 / 结算 ----
    task: Task | None = None
    run_goals: list[Task] | None = None
    """run 级边界的初始目标栈（`observe` 的 goals 是 Goal，
    两处词表不同，各用各的字段）。"""
    outcome_run: RunResp | None = None
    outcome_episode: FromRunHarnessToEpisodeHarnessRunResp | None = None

    # ---- 决策 / 观测 ----
    obs: Observation | None = None
    goals: list[Goal] | None = None
    action: Action | None = None
    names: list[str] | None = None

    # ---- 记忆 ----
    memories: list[StepMemory] | None = None
    known_objects: str = ""
    knowledge: str = ""
    knowledge_sources: list[str] | None = None
    episode_memories: list[EpisodeMemory] | None = None
    read_kind: str | None = None
    count: int | None = None
    refs: str | None = None
    entry: StepMemory | None = None
    memory: EpisodeMemory | None = None
    event: ObjectFactEvent | None = None
    reason: str | None = None

    # ---- 判定 / 校验 / 规划结论 ----
    verdicts: list[StepVerifyVerdict] | None = None
    done: bool | None = None
    success: bool | None = None
    stalled: bool | None = None
    checked: int | None = None
    unreliable: int | None = None
    pushed: list[str] | None = None

    # ---- 图控制记账 ----
    stall_key: str | None = None
    stall_count: int | None = None
    text: str | None = None
    next_step: int | None = None
    status: str | None = None
    """这一键之后世界的状态摘要（RAM 档读得出）。链内每按一个键都有一条
    `AFTER_ACTION`，它比 `ACT` 晚一格——`ACT` 写在按键那一刻，那时世界还没动。"""
    stop: str | None = None
    """这一键的结局（`StopReason.value`）：**只在 `ACTION_TRUNCATED` 上**，
    答"为什么截断"。观察账 `AFTER_ACTION` 不带它——"看到什么"与"据此处置了什么"
    是两笔账（前者每键一条、后者只在真丢键时一条）。"""
    dropped: list[ActionSegment] | None = None
    """`ACTION_TRUNCATED` 上被丢掉的那几段（`apply_stop` 截断队列时移除的键）。
    **非空才是"真的截断了"**——`blocked` 可能一个键都不用丢，那时不写这条账。"""
    # ---- CHECKPOINT_RESTORE / CHECKPOINT_SAVE 专用 ----
    restored_episode_id: str | None = None
    restored_step: int | None = None
    cursor: int | None = None
    saved_step: int | None = None
