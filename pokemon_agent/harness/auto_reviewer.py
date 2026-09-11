"""`AutoContinueReviewer`：`HumanReviewer` 的占位实现——永远自动继续。

保证装配出的 run 不被打断地跑完初始栈。**前端接入后替换**（见
`harness/interface/human_reviewer.py`）。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerReviewReq,
    FromHarnessToReviewerReviewResp,
)

from .interface import HumanDecision


class AutoContinueReviewer:
    """占位实现：每个 episode 之间都答复"继续"。"""

    def review(self, req: FromHarnessToReviewerReviewReq) -> FromHarnessToReviewerReviewResp:
        """永远返回 `CONTINUE`，不看上下文。"""
        return FromHarnessToReviewerReviewResp(decision=HumanDecision.CONTINUE)
