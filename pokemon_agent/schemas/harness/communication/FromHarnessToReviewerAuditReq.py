"""`FromHarnessToReviewerAuditReq` / `FromHarnessToReviewerAuditResp`：**审**。

**审是什么**（`docs/PLAN_console_reviewer.md` §2）：人对一个**已给的单一结论**
不满意 → 直接表态（认 / 推翻）。全项目**只有 `review` 节点**用它——
因为只有它面对的答案是单一结论（这一局成还是败），人能自己对它表态；
其余落点面对的都是多字段结构体，只能插话让 LLM 重填。

**与插话的关键区别在返回值**：插话回一句字符串（交给 LLM 当材料），
审回一个 `AuditVerdict`（**人自己的决定**，不经过 LLM）。

**人不写状态**：`AuditVerdict` 只说"认 / 推翻"，落到目标表上的状态改写
（`COMPLETED` / `FAILED`）仍由 harness 盖章——见 `GoalStatus` 的权限表。
`docs/PLAN_console_reviewer.md` §4.3。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import TraceEvent

from .FromRunHarnessToEpisodeHarnessRunResp import FromRunHarnessToEpisodeHarnessRunResp


class AuditVerdict(StrEnum):
    """人对一条结论的表态。**只有两个值**——"认"与"推翻"。"""

    ACCEPT = "accept"
    """认账：接受这条结论，harness 照它盖章。"""
    OVERTURN = "overturn"
    """推翻：这条结论不对（模型幻读），harness 按相反方向盖章。"""


class FromHarnessToReviewerAuditReq(BaseModel):
    """交给人的审查上下文：一局跑完了，看它算成算败。

    `outcome` 是这一局的机械结算（成功/失败、步数、原因）；`episode_trace`
    是这一局的**完整** trace——一次请求自带审查所需的全部依据，人不用再额外问。
    """

    run_id: str = Field(description="这次 run 的标识")
    episode_id: str = Field(description="刚跑完那一局的标识")
    outcome: FromRunHarnessToEpisodeHarnessRunResp = Field(
        description="本局的机械结算（判成/判败的原始依据）"
    )
    episode_trace: list[TraceEvent] = Field(
        default_factory=list,
        description="刚跑完那一局的完整 trace（单 episode，不是全量 run trace）",
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
