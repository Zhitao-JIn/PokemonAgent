"""`NullReviewer` / `NullPlanner`：**不接任何策略对象**时的默认实现。

**它们取代了旧的 `AutoContinueReviewer`**（那个类随槽机制一起删掉了）。
语义等价于"人从不插话、从不推翻、planner 从不表态"：

- `NullReviewer.inject()` 恒返回空串（没有意见）；
- `NullReviewer.audit()` 恒返回认账；
- `NullPlanner.plan()` 恒返回空产出（不新增、不改已有条目、不判收手）。

于是 run 的行为 = LLM 出什么就是什么，目标表只由初始那批目标驱动，
跑完就结束。**这条路上没有任何自动重试预算**——这是删掉
`MAX_GOAL_RETRIES` 的代价（用户已接受，见 `docs/PLAN_console_reviewer.md` §6）：
一个目标跑一局，失败就停在 `FAILED` 等 plan 表态，而 `NullPlanner` 不表态，
表末检于是判 done。

**它现在的实际出场位置**：`auto_push_goals=False` 时 `plan` 节点**根本不会
调 planner**（那一版注定不新增目标，何必花一次模型调用）——所以无头核对
脚本（`check_harness.py`）走的就是这条路。`build.py` 在没有显式传入
`planner` 时装配的是 `BrainPlanner`（模型自主规划），不再是这里。

**为什么两个一起住这里**："不接策略对象"是同一个装配决策的两半——既要一个
不说话的 `Reviewer`、也要一个不表态的 `Planner`，分开住会让 `build.py` 的
装配散成两处。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
)

from .interface.planner_context import PlannerContext
from .interface.planner_outcome import PlannerOutcome


class NullReviewer:
    """无头实现：不插话、不推翻。"""

    def inject(self, req: FromHarnessToReviewerInjectReq) -> str:
        """恒返回空串——人没有意见。"""
        return ""

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """恒认账——接受模型/判定器给的结论。"""
        return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT)


class NullPlanner:
    """无头实现：不新增目标、不改已有条目、不判定收手。"""

    def plan(self, ctx: PlannerContext) -> PlannerOutcome:
        """恒返回空产出——"我没有意见"（这会让表末检按表的状态自己判）。"""
        return PlannerOutcome()


__all__ = ["NullPlanner", "NullReviewer"]
