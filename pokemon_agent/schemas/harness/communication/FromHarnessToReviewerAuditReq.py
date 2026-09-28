"""`FromHarnessToReviewerAuditReq`：harness → `Reviewer.audit()` 的**审**请求。

**审是什么**：人对一个**已给的单一结论**表态（认 / 推翻）。四个审点全在
`review_and_judge` 格：run 审一局、episode 审一个 task（机械结算），以及两层
各审一次 judge 的「已达成」裁决（`docs/web_reviewer/spec.md` §4）。

**人不写状态**：`AuditVerdict` 只说认或推翻，落到表上的状态改写由 harness 盖章。
回话见 `FromHarnessToReviewerAuditResp`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import TraceEvent
from pokemon_agent.schemas.harness.domain.episode_io import EpisodeOutput
from pokemon_agent.schemas.harness.domain.task_io import TaskOutput

from .FromHarnessToBrainToolJudgeResp import FromHarnessToBrainToolJudgeResp


class FromHarnessToReviewerAuditReq(BaseModel):
    """交给人的审查上下文：被审的结论 + 它的依据。

    `outcome` 三选一：一局的机械结算（`EpisodeOutput`）、一个 task 的机械结算
    （`TaskOutput`）、本层 judge 的裁决（`FromHarnessToBrainToolJudgeResp`）。
    `events` 是被审对象自己的 trace——一次请求自带审查所需的全部依据。
    审 task 时 `task_id` 非空。
    """

    run_id: str = Field(description="这次 run 的标识")
    episode_id: str = Field(description="被审对象所在的局（run 层审裁决时放 run_id）")
    task_id: str | None = Field(default=None, description="审 task 时是那个 task 的标识")
    outcome: EpisodeOutput | TaskOutput | FromHarnessToBrainToolJudgeResp = Field(
        description="被审的结论：机械结算，或 judge 的裁决"
    )
    events: list[TraceEvent] = Field(
        default_factory=list,
        description="被审对象自己的 trace（那一局 / 那个 task / 那次 judge 调用的，不是全量）",
    )


__all__ = ["FromHarnessToReviewerAuditReq"]
