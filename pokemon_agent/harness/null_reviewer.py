"""`NullReviewer`：**不接策略对象**时的默认实现。

**它取代了旧的 `AutoContinueReviewer`**（那个类随槽机制一起删掉了）。
语义等价于"人从不插话、从不推翻"：

- `NullReviewer.inject()` 恒返回空串（没有意见）；
- `NullReviewer.audit()` 恒返回认账。

于是 run 的行为 = LLM 出什么就是什么。**这条路上没有任何自动重试预算**——
这是删掉 `MAX_GOAL_RETRIES` 的代价（用户已接受，见 `docs/PLAN_console_reviewer.md`
§6）：一个目标跑一局，失败就停在 `FAILED` 等 plan 表态；无头时没人插话，
模型的下一版规划说了算。

**历史上的另一半**：这里原先还住着 `NullPlanner`（"不问 planner"的空实现，
check_harness 靠它做零规划调用）。0922 第 184 条撤销 `planner` 族后它随之下岗——
要恢复"零规划调用"，给 tool 层的 PlanPort 加一个空实现即可（能力对象化的下一步）。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
)


class NullReviewer:
    """无头实现：不插话、不推翻。"""

    def inject(self, req: FromHarnessToReviewerInjectReq) -> str:
        """恒返回空串——人没有意见。"""
        return ""

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """恒认账——接受模型/判定器给的结论。"""
        return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT)


__all__ = ["NullReviewer"]
