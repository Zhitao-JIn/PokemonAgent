"""`HumanReviewer`：run 级 human-in-the-loop 的审查接口。

每个 episode 之间，`RunHarness.review` 节点调它：把 `HumanReviewReqFromHarness`
（run 到哪了、各局成败、当前栈）交给人类，拿回 `HumanReviewRespFromFrontend`
（继续 / 停止 / 重试）。加/改/删目标统一走 `POST /runs/{id}/goals`，
不是这里的一个决策分支。

**实现由前端（人机界面）提供**——本仓只带"自动继续"的占位实现
（`harness/auto_reviewer.py`），保证 run 不被打断地跑。测试注入假实现。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.communication import (
    HumanReviewReqFromHarness,
    HumanReviewRespFromFrontend,
)


@runtime_checkable
class HumanReviewer(Protocol):
    """run 级的人类审查者：读上下文，回决策。"""

    def review(self, req: HumanReviewReqFromHarness) -> HumanReviewRespFromFrontend:
        """审查上一局的结果，决定下一步。

        req：递给人类的上下文（run_id / 已完成结算 / 当前栈 / 刚跑完的目标）。
        后置条件：永远返回一个决策（continue / stop / retry）。不抛异常——
            人类没答复就算继续。
        """
        ...
