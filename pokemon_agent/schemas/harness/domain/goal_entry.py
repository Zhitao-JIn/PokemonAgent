"""`GoalEntry`：run 级目标表的一行（跨层契约，与 `TraceEvent` 同级）。

**为什么 `Task` 一字不改**：状态是 run 级**编排**概念，不是任务本体的属性。
`Task` 还出现在 `WorldPort.reset()` / `GameToolPort.reset()` 的签名里，往里塞
状态会把 run 级的编排词汇漏进 world。

**goal 可以反复派**（planner 重开失败的目标），所以比 `TaskEntry` 多两列：`attempts`
（派过几次）与 `last_episode_id`（最近一次派发的局，回查结算与记忆的指针）。
`FAILED` / `ABANDONED` 的条目**留在表里**，`note` 就是教训。

**表为准**：`status` 是最终定案（含人审推翻），记忆的章保留机器判定；两者不同时
`overturned=True`，planner 读到的成败一律以表为准。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task

from .entry_status import EntryStatus


class GoalEntry(BaseModel):
    """目标表的一行：一个任务 + 它在 run 内的状态与追踪信息。

    字段注释里的"权威"读法见 `docs/PLAN_console_reviewer.md` §4.3 那张权限表。
    """

    task: Task = Field(description="任务本体（brain 的领域模型，一字不改）")
    status: EntryStatus = Field(
        default=EntryStatus.PENDING,
        description="编排状态。**至多一条 `RUNNING`**（dispatch 盖、review_and_judge 定案）",
    )
    attempts: int = Field(
        default=0,
        description="已派发次数（原来是平行列表，现在贴着目标走）。"
        "它不再被任何上限截断——'要不要再试'是 plan 读表后的决策，不是常量",
    )
    last_episode_id: str | None = Field(
        default=None,
        description="最近一次派发 → 回查 step_memory / trace 的**指针**。"
        "`COMPLETED`/`FAILED` 的条目这一列必须非空——没有来源的状态等于不可追溯的断言",
    )
    note: str = Field(
        default="",
        description="放弃/重开的理由（人或模型给的）。弃掉的条目留表时，这一列就是**教训**",
    )
    overturned: bool = Field(
        default=False,
        description="这条定案是人审推翻来的（与记忆里的机器判定相反）；理由在 `note`",
    )


__all__ = ["GoalEntry"]
