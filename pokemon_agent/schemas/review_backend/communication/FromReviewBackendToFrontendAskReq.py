"""`FromReviewBackendToFrontendAskReq`：跳 B（后端 → 网页）推一问。无回话。

后端把跳 A 的插话 / 审请求摊平成这一封广播给所有网页；网页重连时后端补发当前待答的那一封。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromReviewBackendToFrontendAskReq(BaseModel):
    """一问待答。

    kind：`inject` 时 `body` 是表单文本、`events` 为空；`audit` 时 `body` 是结论文本。
    deadline：到这个 Unix 时刻还没人答，后端按默认值作废。
    """

    msg: Literal["ask"] = Field(default="ask", description="消息标签：`/ui` 上据此分流")
    seq: int = Field(ge=1, description="后端给这一问的编号")
    run_id: str = Field(description="哪次 run 在问")
    kind: Literal["inject", "audit"] = Field(description="插话还是审")
    prompt: str = Field(description="给人看的说明")
    form_kind: str = Field(default="", description="表单种类 / 被审对象种类")
    body: str = Field(description="渲染好的表单或结论文本")
    events: list[str] = Field(default_factory=list, description="被审对象的事件，一条一行")
    episode_id: str | None = Field(default=None, description="审时：被审对象所在的局")
    task_id: str | None = Field(default=None, description="审 task 时：那个 task")
    deadline: float | None = Field(
        default=None, description="作废时刻（Unix 秒）；None = 无倒计时（人模式，由人决定何时答）"
    )


__all__ = ["FromReviewBackendToFrontendAskReq"]
