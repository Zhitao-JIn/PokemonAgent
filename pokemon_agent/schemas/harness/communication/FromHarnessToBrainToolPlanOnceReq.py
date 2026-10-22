"""run 级规划请求：目标表、全部局详情、过往 run 背景、地图事实、知识与当前画面。

harness 只装素材，门面负责渲染 prompt 与从详情收集首末帧。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.harness.domain import GoalEntry, JudgeFeedback
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, RunMemory
from pokemon_agent.world import TaskObservation


class FromHarnessToBrainToolPlanOnceReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的规划请求。

    run_id：这次 run 的标识（trace 记账用，大脑不需要）。
    plan：当前**目标表**，表序 = 先后顺序（第一条待做的最先被派发）。
        每一行带自己的 `status`/`attempts`/`note`/`overturned`——模型据此看见
        "哪些做过了、成没成、为什么没成"。
    details：本 run 全部局，按执行顺序，与 judge·L0 共用同一份详情。
    run_index：过往 run 的一行背景，不含本 run，不限定 run_goal。
    knowledge：本圈检索到的领域知识全文。
    observation：本圈 RAM 当前画面；尚未取得时为 None。
    objects：本 run 涉及的地图交互事实（`object_memory`，锚在 `(map_id,x,y)` 上，
        跨局共池）。run 级按**可选条件**取
        （`query_object_events(map_id=None)`）。
    last_judge：判定员上一次对 run 目标的看法，及人是否推翻、推翻理由；还没判过为 None。
    max_push：这一次最多新增几个目标。**提示模型的建议上限，不是截断**——
        `plan` 节点不再替模型裁剪（裁掉就是静默丢目标）。

    图不是本信封的字段，由 Planner 从 details 的首末帧拼出，
    与 judge / choose 同样由门面掌握图的组装。
    """

    run_goal: Goal
    remaining_planning_rounds: int | None = None
    execution_order: list[str] = Field(default_factory=list)
    run_id: str
    plan: list[GoalEntry]
    details: list[EpisodeMemory] = Field(
        default_factory=list, description="本 run 全部局，与 judge·L0 同一份"
    )
    run_index: list[RunMemory] = Field(
        default_factory=list, description="过往 run 的一行背景，不含本 run"
    )
    knowledge: list[str] = Field(default_factory=list)
    observation: TaskObservation | None = None
    objects: list[ObjectFactEvent] = Field(default_factory=list)
    last_judge: JudgeFeedback | None = Field(
        default=None, description="上一次 run 判定及人的表态；还没判过为 None"
    )
    max_push: int
    human_note: str = Field(default="", description="人对上一版规划的插话；空 = 没被插话")
