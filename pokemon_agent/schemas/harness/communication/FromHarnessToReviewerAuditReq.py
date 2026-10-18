"""`FromHarnessToReviewerAuditReq`：harness → `Reviewer.audit()` 的**审**请求。

**审是什么**：人对一个**已给的单一结论**表态（认 / 推翻）。两个审点全在
`review_and_judge` 格：run 与 episode 各审一次 judge 的「已达成」裁决
（`docs/web_reviewer/spec.md` §4）。

**人不写状态**：`AuditVerdict` 只说认或推翻，harness 据此接受裁决或记录推翻理由。
回话见 `FromHarnessToReviewerAuditResp`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import TraceEvent
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from .FromHarnessToBrainToolJudgeResp import FromHarnessToBrainToolJudgeResp


class FromHarnessToReviewerAuditReq(BaseModel):
    """交给人的审查上下文：被审的结论 + 它的依据。

    `outcome` 是本层 judge 的裁决（`FromHarnessToBrainToolJudgeResp`）。
    `events` 是被审对象自己的 trace——一次请求自带审查所需的全部依据。
    """

    context: ReviewContext = Field(description="本次实际大脑请求、定案后的表与计数")
    run_id: str = Field(description="这次 run 的标识")
    episode_id: str = Field(description="被审对象所在的局（run 层审裁决时放 run_id）")
    outcome: FromHarnessToBrainToolJudgeResp = Field(description="被审的结论：judge 的裁决")
    events: list[TraceEvent] = Field(
        default_factory=list,
        description="本次 judge 调用的 trace，不是全量",
    )


__all__ = ["FromHarnessToReviewerAuditReq"]
