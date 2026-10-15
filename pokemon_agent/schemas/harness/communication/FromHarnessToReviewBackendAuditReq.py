"""`FromHarnessToReviewBackendAuditReq`：跳 A（源程序 → 后端）的**审**请求。

`WebReviewer` 把进程内的 `FromHarnessToReviewerAuditReq` 渲染成纯文本后发这一封。
后端与网页不认识游戏语义，只搬文本。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromHarnessToReviewBackendAuditReq(BaseModel):
    """一次审：被审结论的渲染文本 + 被审对象的事件行。

    form_kind：被审对象（`JudgeVerdict`），页面据此挑面孔。
    timeout_s：后端等人答的秒数；到点由后端回认账、`answered=False`。
    """

    msg: Literal["audit"] = Field(default="audit", description="消息标签：`/harness` 上据此分流")
    run_id: str = Field(description="这次 run 的标识")
    episode_id: str = Field(description="被审对象所在的局（run 层审裁决时放 run_id）")
    prompt: str = Field(description="给人看的说明")
    form_kind: str = Field(description="被审对象的种类")
    outcome_text: str = Field(description="源程序渲染好的结论文本")
    events: list[str] = Field(default_factory=list, description="被审对象的事件，一条一行")
    timeout_s: float | None = Field(
        default=None,
        description="后端等人答的秒数；`None` 表示不自带超时（交前端 / agent 计时）。A5 起可空",
    )


__all__ = ["FromHarnessToReviewBackendAuditReq"]
