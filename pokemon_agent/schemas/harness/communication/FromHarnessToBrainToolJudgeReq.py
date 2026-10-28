"""`FromHarnessToBrainToolJudgeReq`：harness → `BrainTool` 的判定请求。

**只装素材**（目标、历史、截图）——`BrainTool` 自己拼 prompt（`prompts.judge_success`
的 `build_prompt()`）、自己渲染 `history` 文本，再交给大脑。harness 不碰 prompt
（0913 定案："拼 prompt"与"问模型"都在 tool 一处的入口上，不分散两个地方）。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from pokemon_agent.brain.interface import Decomposition, Goal, RunPlan
from pokemon_agent.schemas.harness.domain.goal_entry import GoalEntry
from pokemon_agent.schemas.harness.domain.ram_observation import RamObservation
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    RunMemory,
    TaskMemory,
)
from pokemon_agent.world import TaskObservation


class FromHarnessToBrainToolJudgeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的判定请求。

    goal：要判的目标。
    history：本 task 全部动作记忆（prompt 渲 `$history` 时与决策记忆同一渲染
        滤掉——判定看"发生了什么"，不看决策者的主张）。**要带的截图也由
        `BrainTool.judge()` 从这同一批 history 取**（`dedup_snapshots()`，
        0915 130 收权）——信封不另开 images 通道。
    task_memories：episode 层判定的素材（本局已跑 task 的记忆）；task 层留空。
    task_table：episode 层判定的素材（本局任务表——成败以表为准，含人审推翻）；另两层留空。
    episode_memories：L0 详情，本 run 全部局，与 plan·L0 的 details 共用；下两层留空。
    run_index：L0 背景，过往 run 的一行记录，不含本 run。
    task_index：本 episode 内此前同目标 task 的无帧背景索引，只有 task 层填写。
    episode_index：本 run 内同一个 L1 goal 的其他局背景，只用 index_line 渲染。
    observation：episode / run 层当前画面；task 层留空。
    ram_observations：仅 run 层填写，同执行线最近至多五次已落盘 RAM 读数；不补造历史。
    knowledge：三层各自检索到的领域知识。
    allow_interrupt：只有 task 层置真——prompt 多一段「是不是被打断了」的判法，
        判定员多回答一个 `interrupted`。另两层不问，结果里 `interrupted` 恒为假。


    **`prompt` 不是本模型的字段**（0913 删）：它是 `BrainTool.judge()` 入口处
    调 `build_prompt(req)` 的产物，只活在那一次调用的局部——shell 与"问模型"
    共享同一个 req 这个中间态不再外露。
    **`images` 同样不是本模型的字段**（0915 130 删）：拼图与拼 prompt 同在
    tool 入口，harness 只装素材。
    """

    goal_table: Sequence[GoalEntry] = ()
    latest_planning: RunPlan | Decomposition | None = None
    planning_round: int = 0
    trigger: str = "normal"
    goal: Goal
    history: Sequence[ActMemory] = ()
    task_memories: Sequence[TaskMemory] = ()
    task_table: Sequence[TaskEntry] = ()
    episode_memories: Sequence[EpisodeMemory] = ()
    task_index: Sequence[TaskMemory] = ()
    episode_index: Sequence[EpisodeMemory] = ()
    run_index: Sequence[RunMemory] = ()
    observation: TaskObservation | None = None
    knowledge: str = ""
    allow_interrupt: bool = False

    ram_observations: list[RamObservation] = Field(default_factory=list, max_length=5)

    @model_serializer(mode="wrap")
    def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """历史对象事件保留原信封形状；RAM 空窗口统一输出空列表。"""
        data = handler(self)
        return data
