"""task 图的唯一状态载体：`TaskState`（一键一圈）。

    身份    run_id / episode_id / task / start_step         begin_task 写，全程只读
    计数    step（本 task 已按键数）                         act 写
    感知    task_ctx（当前帧 + 本 task ActMemory + 受限动作空间）  perceive 写
            after_observation（本圈 sense 取的新帧，格内流转） perceive 首单元写、close_step 清
    停摆    stall_key / stall_count                          perceive 写
    决策    action（本圈那一个键）                            plan_task 写，perceive 消费后清
    判定    termination（done / success 由它推出）                     review_and_judge 写
    收尾    act_verdicts / reason / memory / output                 task_done 写

**一圈的数据流**：`perceive` 的 `sense` 取一帧落 `after_observation`（步号 = `start_step + step`）
→ 有 `action`（上一圈按过键）才构造 ActMemory / 停摆 / object 事件 → `close_step` 把新帧转正进
`task_ctx.observation` 并清 `action` → `review_and_judge` → `plan_task` 出一个键 → `act` 按键、
`step+1` → 回 `perceive`。首圈 `action` 为 None：`sense` 取的就是开局帧，直接转正。

活对象一个都不进来（world / tools / brain / trace），它们住 `TaskRuntime`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Action, Task
from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.schemas.harness.domain import Settled, TaskOutput, Termination
from pokemon_agent.schemas.memory import ActMemory, TaskMemory
from pokemon_agent.world import ActionSpace, Observation


class TaskContext(BaseModel):
    """perceive 格的产物束：当前帧 + 本 task 的 ActMemory + 本键受限动作空间。"""

    observation: Observation | None = Field(
        default=None, description="当前帧（下一个键按下之前的那一帧）；首圈 perceive 前为 None"
    )
    action_space: ActionSpace | None = Field(default=None, description="本键允许的动作边界")
    act_memories: list[ActMemory] = Field(
        default_factory=list, description="本 task 已写的全部 ActMemory（按 step 升序）"
    )


class TaskState(Settled, BaseModel):
    """一个 task 的全部可序列化状态（分组见模块文档）。"""

    run_id: str = Field(description="所属 run（ActMemory 归属章）")
    episode_id: str = Field(description="所属 episode（记忆按局分组）")
    task: Task = Field(description="本 task：目标、判据、键预算 `max_steps`")
    start_step: int = Field(
        ge=0, description="本局键号基数——本 task 每一帧的步号 = start_step + step（唯一来源）"
    )

    step: int = Field(
        default=0, ge=0, description="本 task 已按键数——预算判据 `step >= task.max_steps`"
    )

    task_ctx: TaskContext = Field(
        default_factory=TaskContext, description="当前帧 + 动作空间；首圈 perceive 前为空"
    )
    after_observation: Observation | None = Field(
        default=None, description="本圈 sense 刚取的新帧——perceive 格内流转，出格前恒为 None"
    )

    stall_key: str | None = Field(
        default=None, description="上一键的停摆键；None = 还没有可比的历史"
    )
    stall_count: int = Field(default=0, ge=0, description="连续多少键画面与动作都无变化")

    action: Action | None = Field(
        default=None, description="本圈那一个键；perceive 消费后清为 None"
    )

    termination: Termination | None = Field(
        default=None, description="终止类别；None = 还没停（`done` / `success` 由它推出）"
    )
    judge_reason: str = Field(
        default="",
        description="review_and_judge 写的判定依据（判定员的理由 / 机械判停类别）；与 reason 分开",
    )

    act_verdicts: list[VerifyVerdict] = Field(
        default_factory=list, description="与 act_memories 等长的正/负标注——正负都交给蒸馏作参考"
    )
    reason: str = Field(default="", description="task_done 里 LLM 写的结论说明")
    memory: TaskMemory | None = Field(default=None, description="task_done 蒸出并落库的 TaskMemory")
    output: TaskOutput | None = Field(
        default=None, description="task_done 末单元写的结算；task_entry.close 取走"
    )


__all__ = ["TaskContext", "TaskState"]
