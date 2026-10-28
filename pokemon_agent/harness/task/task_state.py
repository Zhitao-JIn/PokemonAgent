"""task 图的唯一状态载体：`TaskState`（一键一圈）。

    身份    run_id / episode_id / task / total_acts        begin_task 写，全程只读
    计数    step（本 task 已按键数）                         act 写
    感知    task_ctx（当前帧 + 本 task ActMemory + 受限动作空间）  perceive 写
            after_observation / after_ram（本圈新帧与其内存读数） sense 写、close_step 清
    停摆    stall_key / stall_count                          perceive 写
    决策    action（本圈那一个键或一条脚本）                  plan_task 写，perceive 消费后清
            last_report / last_outcome / last_observations（上一脚本报告、结局与逐键观察） act 写
    判定    termination（done / success 由它推出）                     review_and_judge 写
    收尾    reason / memory / output                 task_done 写

**一圈的数据流**：`perceive` 的 `sense` 取一帧落 `after_observation`（观测的局内累计键数 =
`total_acts + step`；**账面步号** = `step + 1`，圈号语义：dispatch 落 0、每圈取帧 +1，
同圈所有账共用）
→ 有 `action`（上一圈按过键）才构造 ActMemory / 停摆 → `close_step` 把新帧转正进
`task_ctx.observation` 并清 `action` → `review_and_judge` → `plan_task` 出一个键 → `act` 按键、
`step+1` → 回 `perceive`。首圈 `action` 为 None：`sense` 取的就是开局帧，直接转正。

活对象一个都不进来（world / tools / brain / trace），它们住 `TaskRuntime`。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pokemon_agent.brain import Action, Task
from pokemon_agent.schemas.harness.domain import JudgeFeedback, Settled, TaskOutput, Termination
from pokemon_agent.schemas.memory import ActMemory, TaskMemory
from pokemon_agent.world import ActionSpace, RamReadout, TaskObservation


class TaskContext(BaseModel):
    """perceive 格的产物束：当前帧 + 本 task 的 ActMemory + 本键受限动作空间。"""

    observation: TaskObservation | None = Field(
        default=None, description="当前帧（下一个键按下之前的那一帧）；首圈 perceive 前为 None"
    )
    ram: RamReadout | None = Field(default=None, description="与 observation 同帧的内存读数")
    action_space: ActionSpace | None = Field(default=None, description="本键允许的动作边界")
    act_memories: list[ActMemory] = Field(
        default_factory=list, description="本 task 已写的全部 ActMemory（按 step 升序）"
    )


class TaskState(Settled, BaseModel):
    """一个 task 的全部可序列化状态（分组见模块文档）。"""

    run_id: str = Field(description="所属 run（ActMemory 归属章）")
    episode_id: str = Field(description="所属 episode（记忆按局分组）")
    entry_id: str
    task: Task = Field(description="本 task：目标、判据、父级建议键数 `max_steps`，硬限来自配置")
    total_acts: int = Field(
        ge=0,
        description=(
            "进 task 时定格的局内累计键数快照（episode 派发时带下，task 内恒定）——"
            "观测的局内累计键数 = total_acts + step（帧槽 / ActMemory 键控用）；"
            "账面步号与它解耦（= step + 1，圈号，0928 定稿）"
        ),
    )

    actions_budget: int | None = Field(
        default=None, ge=0, description="开任务时剩余的跨局动作额度；None 不限"
    )
    remaining_s: float | None = Field(
        default=None, ge=0, description="检查点处剩余运行秒数；None 不限"
    )

    task_index: list[TaskMemory] = Field(
        default_factory=list, description="episode 交下来的只读背景：此前同目标 task，task 内不变"
    )
    knowledge: list[str] = Field(
        default_factory=list,
        description="episode 交下来的领域知识全文（task 内只读，每次决策原样带上）",
    )

    step: int = Field(
        default=0,
        ge=0,
        description="本 task 已按键数——预算判据 `step >= config.budget.task_max_steps`",
    )

    task_ctx: TaskContext = Field(
        default_factory=TaskContext, description="当前帧 + 动作空间；首圈 perceive 前为空"
    )
    after_observation: TaskObservation | None = Field(
        default=None, description="本圈 sense 刚取的新帧——perceive 格内流转，出格前恒为 None"
    )

    after_ram: RamReadout | None = Field(
        default=None, description="与 after_observation 同帧的内存读数；close_step 后清空"
    )

    stall_key: str | None = Field(
        default=None, description="上一键的停摆键；None = 还没有可比的历史"
    )
    stall_count: int = Field(default=0, ge=0, description="连续多少键画面与动作都无变化")

    action: Action | None = Field(
        default=None, description="本圈那一个键或一条脚本；perceive 消费后清为 None"
    )
    last_report: dict[str, Any] | None = Field(
        default=None,
        description="上一个动作是脚本时它的终态报告（{ok, code, data, events, calls}）；"
        "其它动作时为 None（act 每次覆盖）",
    )
    last_outcome: ActMemory.ScriptOutcome | None = None
    last_observations: list[ActMemory.Observation.StepObs] = Field(default_factory=list)

    termination: Termination | None = Field(
        default=None, description="终止类别；None = 还没停（`done` / `success` 由它推出）"
    )
    judge_reason: str = Field(
        default="",
        description="review_and_judge 写的判定依据（判定员的理由 / 机械判停类别）；与 reason 分开",
    )

    last_judge: JudgeFeedback | None = Field(
        default=None, description="启用 task 审点时的上次判定与复核意见；随图状态保存"
    )

    reason: str = Field(default="", description="task_done 里 LLM 写的结论说明")
    memory: TaskMemory | None = Field(default=None, description="task_done 蒸出并落库的 TaskMemory")
    output: TaskOutput | None = Field(
        default=None, description="task_done 末单元写的结算；task_entry.close 取走"
    )


__all__ = ["TaskContext", "TaskState"]
