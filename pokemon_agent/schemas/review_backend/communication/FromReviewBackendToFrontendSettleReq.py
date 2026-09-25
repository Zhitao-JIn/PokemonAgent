"""`FromReviewBackendToFrontendSettleReq`：跳 B（后端 → 网页）一问了结。无回话。

网页据此清掉待答卡片、记进历史；重连时后端补发最近若干条。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromReviewBackendToFrontendSettleReq(BaseModel):
    """一问的结局。

    by：`human` 人答了；`timeout` 超时按默认值；`harness_gone` 源程序断开，作废。
    text / verdict / note：最终交回源程序的答案（插话取 text，审取 verdict + note）。
    """

    msg: Literal["settle"] = Field(default="settle", description="消息标签：`/ui` 上据此分流")
    seq: int = Field(ge=1, description="了结的是第几问")
    by: Literal["human", "timeout", "harness_gone"] = Field(description="怎么了结的")
    text: str = Field(default="", description="插话：交回的话")
    verdict: AuditVerdict | None = Field(default=None, description="审：交回的表态")
    note: str = Field(default="", description="审：推翻理由")


__all__ = ["FromReviewBackendToFrontendSettleReq"]
