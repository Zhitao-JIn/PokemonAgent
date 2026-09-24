"""`FromHarnessToReviewerAuditReq` / `FromHarnessToReviewerAuditResp`：**审**。

**审是什么**（`docs/PLAN_console_reviewer.md` §2）：人对一个**已给的单一结论**
不满意 → 直接表态（认 / 推翻）。用在两处盖章前：run 的 `review_and_judge` 审上一局、
episode 的 `review_and_judge` 审上一个 task——它们面对的都是单一结论（成还是败），
人能自己表态；其余落点面对的是多字段结构体，只能插话让 LLM 重填。

**与插话的关键区别在返回值**：插话回一句字符串（交给 LLM 当材料），
审回一个 `AuditVerdict`（**人自己的决定**，不经过 LLM）。

**人不写状态**：`AuditVerdict` 只说"认 / 推翻"，落到目标表上的状态改写
（`COMPLETED` / `FAILED`）仍由 harness 盖章——见 `EntryStatus` 的权限表。
`docs/PLAN_console_reviewer.md` §4.3。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import TraceEvent
from pokemon_agent.schemas.harness.domain.episode_io import EpisodeOutput
from pokemon_agent.schemas.harness.domain.task_io import TaskOutput


class AuditVerdict(StrEnum):
    """人对一条结论的表态。**只有两个值**——"认"与"推翻"。"""

    ACCEPT = "accept"
    """认账：接受这条结论，harness 照它盖章。"""
    OVERTURN = "overturn"
    """推翻：这条结论不对（模型幻读），harness 按相反方向盖章。"""


class FromHarnessToReviewerAuditReq(BaseModel):
    """交给人的审查上下文：一局（或一个 task）跑完了，看它算成算败。

    `outcome` 是它的机械结算（终止类别、计数、结论说明）；`events` 是它的**完整** trace
    ——一次请求自带审查所需的全部依据，人不用再额外问。审 task 时 `task_id` 非空。
    """

    run_id: str = Field(description="这次 run 的标识")
    episode_id: str = Field(description="刚跑完那一局（或那个 task 所在的局）的标识")
    task_id: str | None = Field(default=None, description="审 task 时是那个 task 的标识")
    outcome: EpisodeOutput | TaskOutput = Field(description="机械结算（判成/判败的原始依据）")
    events: list[TraceEvent] = Field(
        default_factory=list,
        description="被审对象自己的完整 trace（那一局或那个 task 的，不是全量 run trace）",
    )


class FromHarnessToReviewerAuditResp(BaseModel):
    """人的表态。

    `verdict` 是认还是推翻；`note` 是推翻时给的**纠正理由**——它会被拼进
    后续提示词的**最末尾**（用户定调："在最末尾放"），当作一条最高优先级的
    人类纠正，压过其余规则。
    """

    verdict: AuditVerdict = Field(description="认账 / 推翻")
    note: str = Field(
        default="",
        description="推翻时的纠正理由（拼在提示词最末尾）；认账时为空",
    )


__all__ = [
    "AuditVerdict",
    "FromHarnessToReviewerAuditReq",
    "FromHarnessToReviewerAuditResp",
]
