"""episode 图的唯一状态载体：`EpisodeRunState`（一 task 一圈）。

    身份    run_id / episode_id / goal                        begin_episode 写，全程只读
    计数    step（已派 task 数） / total_acts（累计键数）         act 写 / perceive 写
            fail_streak（连续失败 task 数）                     perceive 写
    感知    ep_ctx（当前帧 + 本局 TaskMemory + 跨局摘要 + 知识 + 物件）  perceive 写
            pending_task（刚跑完的 TaskOutput，格间流转）        act 写、perceive 吸收后清
            task_outputs（本局全部 TaskOutput）                 perceive 写
    规划    tasks（任务表 TaskEntry）   plan_episode 追加、act 标 RUNNING、review 盖章
    判定    termination（done / success 由它推出）              review_and_judge 写
    收尾    task_verdicts / reason / memory / output            episode_done 写

**一圈的数据流**：`act` 弹队首、拼 `TaskInput`、经 `task_entry.run_task` 跑子图，
只把 `TaskOutput` 写进 `pending_task`、`step+1` → 回 `perceive`：先吸收
`pending_task`（键数、失败连击、`task_outputs`），再 `sense` 取一帧（完整档）、做四路检索。
判定、拆解、收尾都只用 perceive 装好的 `ep_ctx`，不再自己查库。
队列空了 `plan_episode` 才问 decomposer 拆下一串 task。

**预算按本层单位**：`goal.max_steps` 是 **task 数**；`total_acts` 只作
键号基数与统计。活对象一个都不进来，它们住 `EpisodeRuntime`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Goal, Task
from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.schemas.harness import FromHarnessToMemoryToolQueryKnowledgeResp
from pokemon_agent.schemas.harness.domain import (
    EpisodeOutput,
    Settled,
    TaskEntry,
    TaskOutput,
    Termination,
)
from pokemon_agent.schemas.memory import EpisodeMemory, TaskMemory
from pokemon_agent.world import Observation


class EpisodeContext(BaseModel):
    """perceive 格的产物束：这一圈判定与规划的全部输入。"""

    observation: Observation | None = Field(
        default=None, description="本圈 sense 取的当前帧（完整档）；进图前为 None"
    )
    task_memories: list[TaskMemory] = Field(
        default_factory=list, description="本局全部 TaskMemory（按 start_step 升序）"
    )
    global_episode_memories: list[EpisodeMemory] = Field(
        default_factory=list, description="本 run 的跨局摘要"
    )
    knowledge_semantic_memory: FromHarnessToMemoryToolQueryKnowledgeResp | None = Field(
        default=None, description="知识库检索结果；None = 本局还没查过。之后沿用，到下次重查为止"
    )
    knowledge_scene: str = Field(
        default="", description="上次检索知识时的场景（`facts.scene_value`）；变了就重查"
    )
    knowledge_at_tasks: int = Field(
        default=0, ge=0, description="上次检索知识时已结算的 task 数；此后有 task 失败就重查"
    )
    object_semantic_memory: str = Field(
        default="", description="本图 object 语义记忆文字化（merge 折进 facts）"
    )


class EpisodeRunState(Settled, BaseModel):
    """一局的全部可序列化状态（分组见模块文档）。"""

    run_id: str = Field(description="所属 run")
    episode_id: str = Field(description="本局标识")
    goal: Task = Field(description="本局唯一目标；`max_steps` 单位是 task 数")

    step: int = Field(
        default=0, ge=0, description="已派 task 数——预算判据 `step >= goal.max_steps`"
    )
    total_acts: int = Field(
        default=0, ge=0, description="累计键数：下一个 task 的 start_step，也是统计量"
    )
    fail_streak: int = Field(
        default=0, ge=0, description="连续失败 task 数——停摆判据 `>= EPISODE_STALL_LIMIT`"
    )

    ep_ctx: EpisodeContext = Field(description="当前帧 + 四路检索；begin_episode 放开局帧")
    pending_task: TaskOutput | None = Field(
        default=None, description="刚跑完的 task 结算；perceive 吸收后清"
    )
    task_outputs: list[TaskOutput] = Field(
        default_factory=list, description="本局全部 task 结算，按执行序"
    )

    tasks: list[TaskEntry] = Field(
        default_factory=list,
        description="任务表：本局拆出的全部 task（表序 = 派发顺序；至多一条 RUNNING）；"
        "没有 PENDING = plan_episode 该拆下一版",
    )

    termination: Termination | None = Field(
        default=None, description="终止类别；None = 还没停（`done` / `success` 由它推出）"
    )
    judge_reason: str = Field(
        default="",
        description="review_and_judge 写的判定依据（判定员的理由 / 机械判停类别）；与 reason 分开",
    )

    task_verdicts: list[VerifyVerdict] = Field(
        default_factory=list, description="与 task_memories 等长的正/负标注——正负都交给蒸馏作参考"
    )
    reason: str = Field(default="", description="episode_done 里 LLM 写的结论说明")
    memory: EpisodeMemory | None = Field(
        default=None, description="episode_done 蒸出并落库的 EpisodeMemory"
    )
    output: EpisodeOutput | None = Field(
        default=None, description="episode_done 末单元写的结算；episode_entry.close 取走"
    )


def current_goal(state: EpisodeRunState) -> Goal:
    """本局判据与决策共用的 `Goal`（`state.goal` 的判据形态）。"""
    return Goal(goal=state.goal.goal, criteria=state.goal.success_criteria)


def current_knowledge(state: EpisodeRunState) -> list[str]:
    """本圈 perceive 检索到的领域知识全文，一篇一条；没查到给空列表。

    拆解（`plan_episode`）与派发（`act` 带进 `TaskInput`）共用这一份，不各自再取。
    """
    hit = state.ep_ctx.knowledge_semantic_memory
    return list(hit.contents) if hit is not None else []


__all__ = ["EpisodeContext", "EpisodeRunState", "current_goal", "current_knowledge"]
