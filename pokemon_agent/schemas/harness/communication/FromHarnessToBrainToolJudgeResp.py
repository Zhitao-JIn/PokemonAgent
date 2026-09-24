"""`FromHarnessToBrainToolJudgeResp`：`BrainTool` → harness 的判定响应。

字段同 `JudgeResult`（brain 的原生契约）——两套契约独立维护，互转由
`BrainTool.judge()` 显式完成。`calls` 是整条重试链的账。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .ModelCall import ModelCall


class FromHarnessToBrainToolJudgeResp(BaseModel):
    """`BrainTool.judge()` 交回给 harness 的判定结果。

    **拿不到结果时抛 `MaxRetriesExceeded`**（整条账在异常里）——旧契约的
    "永远不抛异常、失败返回 `done=False`"已废弃：那会让"判定器坏了"与
    "真的没达成"在数据里分不开。
    """

    done: bool = Field(description="任务达成了没有")
    interrupted: bool = Field(
        default=False,
        description="task 被意外打断（只在 `allow_interrupt` 时可能为真；`done` 为真时恒为假）",
    )
    why: str = Field(description="看到了什么证据（或为什么证据不足）")
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )
