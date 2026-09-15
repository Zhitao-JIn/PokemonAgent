"""`FromHarnessToReviewerInjectReq`：harness → `Reviewer.inject()` 的**插话**请求。

**插话是什么**（`docs/PLAN_console_reviewer.md` §2）：人对 LLM 返回的**多字段结构体**
不满意 → 说一句 → **LLM 带着这句话重填**。这个信封装的正是"亮给人看的那张表单"
——`form` 是那个结构体（`Action` / 裁决 / goals 表……），`问什么` 用 `prompt` 说。

**`form` 是 `Any` 而不是具体类型**（这是个刻意的取舍）：插话要挂在若干**不同的**
结构体上（`Action`、judge 裁决、goals 表），给每一种开一个信封会让
`Reviewer` Protocol 的方法签名里出现一个联合类型；而 `Reviewer` 只负责
"把表单亮给人、收一句反馈"，**它不认识那些结构体的语义**。所以这里用
`Any` + 一个 `form_kind` 标签，渲染由调用方节点自己决定（人看到的是控制台
里现拼的文本，不是 Pydantic 序列化）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromHarnessToReviewerInjectReq(BaseModel):
    """一次插话请求：把"表单"（一个结构体的当前版本）亮给人。

    `prompt` 是给**人**看的说明（"这是这一步打算做的动作，看对不对"）；
    `form` 是那个结构体本体；`form_kind` 是它的类型标签（`"action"` /
    `"verdict"` / `"goals"` ……），供实现方决定怎么渲染，也进 trace 便于复盘。
    """

    prompt: str = Field(description="给人看的说明：这张表单是什么、要人看什么")
    form: Any = Field(description="亮给人的结构体本体（调用方按 form_kind 渲染成文本）")
    form_kind: str = Field(
        default="",
        description="结构体类型标签（action / verdict / goals …），渲染与复盘用",
    )


__all__ = ["FromHarnessToReviewerInjectReq"]
