"""`ReviewerTool`：harness 侧复核席客户端的接线工厂，与 `BrainTool.build` 同形。

装配点只递 `review` 配置段；是否接独立 reviewer 进程由 `mode` 决定（`off` 无头走
`NullReviewer`），客户端实现（`RemoteReviewer`）的选型知识收在这里。reviewer 进程本身
另行启动、读同一份配置——这里只造 harness 一侧的客户端，不起进程。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pokemon_agent.reviewer_link import RemoteReviewer

if TYPE_CHECKING:
    from pokemon_agent.harness import Reviewer
    from pokemon_agent.settings import ReviewConfig


class ReviewerTool:
    """复核席客户端工厂；不持有状态。"""

    @staticmethod
    def build(review: ReviewConfig, *, flush: Callable[[], None]) -> Reviewer:
        """`mode == "off"` 返回 `NullReviewer`，否则连 `review.link_url`。

        `flush` 是 trace 的落盘钩子，复核前先刷盘让审阅方读到最新账；
        断线降级预算取自 `review.link_lost_timeout_s`。
        """
        if review.mode == "off":
            from pokemon_agent.harness.null_reviewer import NullReviewer

            return NullReviewer()
        assert review.link_url is not None, "ReviewConfig 校验保证非 off 必有 link_url"
        return RemoteReviewer(
            review.link_url, flush=flush, lost_timeout_s=review.link_lost_timeout_s
        )
