"""`ReviewMark`：问人两本账（`review_inject` / `review_audit`）的正文素材。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewMark(BaseModel):
    """一次问人的回话。插话取 `form_kind` + `reply`；审取 `form_kind` + `verdict` + `note`。

    `answered` / `wait_s` 两本账都填：分得清"人认账"与"没人答"，也量得出人要多久。
    """

    form_kind: str = Field(
        default="",
        description="亮给人的是什么：插话是表单种类；审是被审对象"
        "（`EpisodeOutput` / `TaskOutput` / `JudgeVerdict`）",
    )
    reply: str = Field(default="", description="插话：人说的话；空串 = 没意见")
    verdict: str = Field(default="", description="审：认 / 推翻（`AuditVerdict` 的值）")
    note: str = Field(default="", description="审：推翻时的理由")
    answered: bool = Field(description="人真的答了；False = 没人答（超时 / 断连 / 无人值守）")
    wait_s: float = Field(description="从亮给人到拿到回话的秒数")
