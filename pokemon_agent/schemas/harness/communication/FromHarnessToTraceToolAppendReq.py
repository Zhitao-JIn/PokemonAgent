"""harness → `TraceTool` 的记账请求协议：`FromHarnessToTraceToolAppendReq`。

harness 只负责组装——从这一步手头的领域对象里挑出本笔账需要的字段、声明
`kind`；tool 对 req 做处理（按 kind 渲染 payload、必要时一拆多），模块
（`TracePort` 的实现）只收渲染好的五元组。

**按 `kind` 分派、不按领域对象类型分派**：同一个类型产出不同事件——
`ModelCall` 可以是决策账单（attempt）/判定账单（depth+why）/校验账单
（verdicts），`StepMemory` 有读（一批）有写（单条）；类型名决定不了格式，
"这是哪笔账"只有调用方知道。

各 kind 必填的字段见 `tools/trace_render.py` 每个渲染函数入口的 assert；
payload 字段格式是跨模块契约（观测台前端按字段名渲染），变更权在 tool 层。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.providers.interface import ModelCall
from pokemon_agent.schemas.brain import (
    ActionFromBrain,
    GoalForBrain,
    StepVerifyVerdict,
    TaskForBrain,
)
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, StepMemory
from pokemon_agent.schemas.trace import Source
from pokemon_agent.schemas.world import ObservationFromWorld
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
    task: TaskForBrain | None = None
    run_goals: list[TaskForBrain] | None = None
    """run 级边界的初始目标栈（`observe` 的 goals 是 GoalForBrain，
    两处词表不同，各用各的字段）。"""
    outcome_run: RunResp | None = None
    outcome_episode: FromRunHarnessToEpisodeHarnessRunResp | None = None

    # ---- 决策 / 观测 ----
    obs: ObservationFromWorld | None = None
    goals: list[GoalForBrain] | None = None
    action: ActionFromBrain | None = None
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
    scene: str | None = None
    overlay: str | None = None
    status: str | None = None
    # ---- CHECKPOINT_RESTORE 专用 ----
    restored_episode_id: str | None = None
    restored_step: int | None = None
    cursor: int | None = None
