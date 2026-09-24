"""`PlannerOutcome` / `GoalUpdate`：brain 那一版规划（`RunPlan`）的 run 级形态。

**它不是"目标表"，是"对目标表的意见"**——`plan` 节点才是表的唯一写入点，
产出两路：新增条目（`entries`）、对已有条目的状态表态（`updates`）。
收手不归规划——停机只由 run 的 `review_and_judge` 判。

## 为什么分成两路而不是"返回整张新表"

让模型重写整表，漏抄一条就是**静默丢目标**（项目铁律里明确点过的静默失败）。
分成"新增 + 定点更新"之后：表里没被提到的条目原样不动，
每条变更都指名道姓（`task_id`），漏了谁一目了然。

## `updates` 的权限边界（权限表见 `EntryStatus` 的类 docstring）

`status` 这个字段不是谁都能写的：`COMPLETED`/`FAILED` 是**机械事实**（本局到底
成没成），只能由 harness 从 `outcome.success` 推导；模型和人能写的是**主观决策**
——"这条我不做了"（`ABANDONED`）、"这条我想重开"（`PENDING`）。
所以 `updates` 里允许的值只有这两个，别的值在 `plan` 节点入口就被拦下
（`ALLOWED_UPDATE_STATUSES`）。这不是"暂时没实现"的省略，是 R2
（「必须为真的判断走机械来源，不走 LLM 叙述」）在这一层的落点。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import EntryStatus, GoalEntry

ALLOWED_UPDATE_STATUSES = frozenset({EntryStatus.PENDING, EntryStatus.ABANDONED})
"""`GoalUpdate.status` 允许出现的值——**主观决策**那一半，机械事实不在此列。"""


class GoalUpdate(BaseModel):
    """对**已有条目**的一次状态表态（定点，不重写整表）。"""

    task_id: str = Field(min_length=1, description="要改哪一条（目标表里的 `task_id`）")
    status: EntryStatus = Field(description="改成什么状态；只允许 `PENDING` / `ABANDONED`")
    note: str = Field(
        default="", description="为什么（放弃/重开的理由）。它会随条目留在表里，成为**教训**"
    )


class PlannerOutcome(BaseModel):
    """`plan` 节点从 `planner.plan()` 的 `RunPlan` 翻出来的一版：新增 + 定点更新。

    `entries`：要**追加**到表尾的新目标（按先后顺序，第一条最先被派发）。
    `updates`：对已有条目的状态表态（只允许重开与放弃，见模块 docstring）。
    `why`：一句话规划理由（也是记账里那句话）。
    """

    entries: list[GoalEntry] = Field(
        default_factory=list, description="追加到表尾的新目标（未落表，`PENDING`）"
    )
    updates: list[GoalUpdate] = Field(
        default_factory=list, description="对已有条目的状态表态（重开 / 放弃）"
    )
    why: str = Field(default="", description="决策说明")
    input: str | None = Field(default=None, description="发给模型的请求原文（无模型路径为空）")
    output: str | None = Field(default=None, description="模型吐回的原文（无模型路径为空）")


__all__ = ["ALLOWED_UPDATE_STATUSES", "GoalUpdate", "PlannerOutcome"]
