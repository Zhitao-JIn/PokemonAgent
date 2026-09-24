"""run 图的唯一状态载体：`RunState`（一局一圈）。

    身份    run_id / run_goal / goals              new_run 写；goals 另由 plan_run/review 改
    计数    step（已派局数）/ fail_streak          act 写 / perceive 写（人审推翻时 review 修正）
    感知    plan_ctx（局索引 + 详情 + 地图事实）    perceive 写
            pending_episode（刚跑完的结算）        act 写，perceive 吸收后清
            episode_outputs（全部结算）            perceive 写
    交界    episode_input（本局入参）              act 的 dispatch 写
    判定    termination（done / success 由它推出）           review_and_judge 写

**停机只由 `review_and_judge` 判**：机械三类（世界结束 / 连续失败局 ≥ RUN_STALL_LIMIT /
已派局数 ≥ RUN_MAX_EPISODES）或模型判 `run_goal` 达成。`plan_run` 不再写 done。
活对象一个都不进来，它们住 `RunRuntime`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Goal
from pokemon_agent.schemas.harness.domain import (
    EpisodeInput,
    EpisodeOutput,
    GoalEntry,
    Settled,
    Termination,
)
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent


class PlanContext(BaseModel):
    """perceive 格的产物：`plan_run` 与 `review_and_judge` 这一圈的素材。"""

    index: list[EpisodeMemory] = Field(description="本 run 的局索引（按执行顺序）")
    details: list[EpisodeMemory] = Field(description="详情预取（最近 1 局 + 全部失败局）")
    objects: list[ObjectFactEvent] = Field(description="地图交互事实")


class RunState(Settled, BaseModel):
    """一个 run 的全部可序列化状态（分组见模块文档）。"""

    run_id: str = Field(description="本 run 标识，trace 按它分组")
    run_goal: Goal = Field(description="run 级总目标——review_and_judge 问模型的靶子")
    goals: list[GoalEntry] = Field(description="目标表（表序 = 派发顺序；至多一条 RUNNING）")

    step: int = Field(default=0, ge=0, description="已派局数——预算判据 `step >= RUN_MAX_EPISODES`")
    fail_streak: int = Field(
        default=0, ge=0, description="连续失败局数——停摆判据 `>= RUN_STALL_LIMIT`"
    )

    plan_ctx: PlanContext | None = Field(
        default=None, description="perceive 写；只在进图第一格时为 None"
    )

    episode_input: EpisodeInput | None = Field(
        default=None, description="本局入参；None = 还没派过"
    )
    pending_episode: EpisodeOutput | None = Field(
        default=None, description="刚跑完的那局结算；perceive 吸收后清"
    )
    episode_outputs: list[EpisodeOutput] = Field(
        default_factory=list, description="全部结算，按执行序——RunResp 的汇总源"
    )

    termination: Termination | None = Field(
        default=None, description="终止类别；None = 还没停（`done` / `success` 由它推出）"
    )
    judge_reason: str = Field(
        default="",
        description="review_and_judge 写的判定依据（判定员的理由 / 机械判停类别）；与 reason 分开",
    )


__all__ = ["PlanContext", "RunState"]
