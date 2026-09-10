"""run 级 human-in-the-loop：复核方交回的决策。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.human_decision import HumanDecision


class FromHarnessToReviewerReviewResp(BaseModel):
    """人类给的决策，`decision` 见 `HumanDecision`。

    加/改/删目标统一走 `POST /runs/{id}/goals`
    （`FromFrontendToRunHarnessSubmitEditReq`，整栈原子替换），
    与“这一轮 episode 怎么办”（continue/stop/retry）分开。
    """

    decision: HumanDecision = Field(description="人类对下一层的决策")
