"""`retry` 与 `request_timeouts_s` 两段：重试预算、退避间隔、tool 层单请求时限。"""

from pydantic import Field

from .base import Section


class RetryConfig(Section):
    """重试预算与退避。

    `brain_max_attempts` 含首次；`backoff_s` 用于非超时失败，`timeout_backoff_s` 是超时后的
    退避起点（逐次翻倍）。
    """

    brain_max_attempts: int = Field(gt=0)
    perception_max_retries: int = Field(gt=0)
    backoff_s: float = Field(ge=0, allow_inf_nan=False)
    timeout_backoff_s: float = Field(ge=0, allow_inf_nan=False)


class RequestTimeoutsConfig(Section):
    """tool 层各链路的单请求时限（秒）。plan / 拆解的时限取 `models.plan.timeout_s`。"""

    choose: float = Field(gt=0, allow_inf_nan=False)
    judge: float = Field(gt=0, allow_inf_nan=False)
    verify: float = Field(gt=0, allow_inf_nan=False)
    summarize: float = Field(gt=0, allow_inf_nan=False)
