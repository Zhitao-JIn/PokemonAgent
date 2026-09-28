"""`FromHarnessToReviewBackendInjectReq`：跳 A（源程序 → 后端）的**插话**请求。

`WebReviewer` 把进程内的 `FromHarnessToReviewerInjectReq` 渲染成纯文本后发这一封；
`form` 本体（Python 对象）不出进程。线上是 JSON，经 WebSocket `/harness` 发送。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromHarnessToReviewBackendInjectReq(BaseModel):
    """一次插话：给人看的说明 + 渲染好的表单文本。

    timeout_s：后端等人答的秒数；到点由后端回默认值（空串、`answered=False`）。
    """

    msg: Literal["inject"] = Field(default="inject", description="消息标签：`/harness` 上据此分流")
    run_id: str = Field(description="这次 run 的标识")
    prompt: str = Field(description="给人看的说明")
    form_kind: str = Field(default="", description="表单类型标签，页面据此挑面孔")
    form_text: str = Field(description="源程序渲染好的表单文本")
    timeout_s: float = Field(gt=0, description="后端等人答的秒数")


__all__ = ["FromHarnessToReviewBackendInjectReq"]
