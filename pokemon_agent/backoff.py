"""模型调用重试的退避间隔。

供 `brain_tool._attempt_loop` 的模型重试使用；间隔取自配置的 `retry` 段。
"""

from __future__ import annotations

from pokemon_agent.settings import RetryConfig


def backoff_seconds(last_timed_out: bool, timeouts: int, retry: RetryConfig) -> float:
    """刚失败的那次之后、下一次尝试之前要睡多久。

    `last_timed_out`：刚失败的那次是不是超时（`ToolTimeout`）。
    `timeouts`：到目前为止一共超时了几次（含刚才那次）。
    不是超时：固定 `retry.backoff_s`；是超时：从 `retry.timeout_backoff_s` 起逐次翻倍
    （起点 2s 时，第 1 次超时后 2s，第 2 次后 4s）。
    前置条件：`last_timed_out` 为真时 `timeouts >= 1`。
    """
    if not last_timed_out:
        return retry.backoff_s
    assert timeouts >= 1, "a timed-out attempt must be counted in `timeouts`"
    return retry.timeout_backoff_s * 2 ** (timeouts - 1)


__all__ = ["backoff_seconds"]
