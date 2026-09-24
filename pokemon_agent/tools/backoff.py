"""模型调用重试的退避间隔。

两个重试循环（`brain_tool._attempt_loop` / `GameTools.perceive_with_retry`）共用。
"""

from __future__ import annotations

from pokemon_agent.config import MODEL_RETRY_BACKOFF_MAX_SECONDS, MODEL_RETRY_BACKOFF_SECONDS


def backoff_seconds(failures: int) -> float:
    """第 `failures` 次失败之后、下一次尝试之前要睡多久：基数起步逐次翻倍，封顶。

    `failures`：到目前为止已经失败了几次（从 1 起）。
    前置条件：`failures >= 1`。
    """
    assert failures >= 1, "backoff_seconds() is only asked after a failure"
    return min(MODEL_RETRY_BACKOFF_SECONDS * 2 ** (failures - 1), MODEL_RETRY_BACKOFF_MAX_SECONDS)


__all__ = ["backoff_seconds"]
