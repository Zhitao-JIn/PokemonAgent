"""模型调用重试的退避间隔。

两个重试循环（`brain_tool._attempt_loop` / `GameTools.perceive_with_retry`）共用。
"""

from __future__ import annotations

from pokemon_agent.config import MODEL_RETRY_BACKOFF_SECONDS, TIMEOUT_RETRY_BACKOFF_SECONDS


def backoff_seconds(last_timed_out: bool, timeouts: int) -> float:
    """刚失败的那次之后、下一次尝试之前要睡多久。

    `last_timed_out`：刚失败的那次是不是超时（`ToolTimeout`）。
    `timeouts`：到目前为止一共超时了几次（含刚才那次）。
    不是超时：固定 `MODEL_RETRY_BACKOFF_SECONDS`；是超时：从 `TIMEOUT_RETRY_BACKOFF_SECONDS`
    起逐次翻倍（第 1 次超时后 2s，第 2 次后 4s）。
    前置条件：`last_timed_out` 为真时 `timeouts >= 1`。
    """
    if not last_timed_out:
        return MODEL_RETRY_BACKOFF_SECONDS
    assert timeouts >= 1, "a timed-out attempt must be counted in `timeouts`"
    return TIMEOUT_RETRY_BACKOFF_SECONDS * 2 ** (timeouts - 1)


__all__ = ["backoff_seconds"]
