"""tool 层的 provider 适配器：保持 brain Protocol，逐请求传递等待上限。"""

from typing import Protocol

from pokemon_agent.brain.schemas import (
    LlmCompleteReq,
    LlmCompleteResp,
    VisionDescribeReq,
    VisionDescribeResp,
)
from pokemon_agent.deadline import Deadline


class TimeoutProvider(Protocol):
    """本适配器消费的传输能力；timeout_s 同时限制 socket 与整个等待。"""

    multimodal: bool

    def complete(self, req: LlmCompleteReq, *, timeout_s: float | None = None) -> LlmCompleteResp:
        """文本单次请求；超时抛 provider 的显式异常。"""
        ...

    def describe(
        self, req: VisionDescribeReq, *, timeout_s: float | None = None
    ) -> VisionDescribeResp:
        """多模态单次请求；超时抛 provider 的显式异常。"""
        ...

    def config(self) -> dict[str, str]:
        """返回不含密钥的配置。"""
        ...


class BudgetProvider:
    """实现 brain 原有 provider 协议；deadline 留在 tool 层，不改变 brain 入参。"""

    def __init__(
        self,
        provider: TimeoutProvider,
        deadline: Deadline | None,
        limit_s: float,
        source: str,
    ) -> None:
        """前置条件：单请求上限为正；依赖均由装配点注入。"""
        assert limit_s > 0
        self._provider = provider
        self._deadline = deadline
        self._limit_s = limit_s
        self._source = source
        self.multimodal = getattr(provider, "multimodal", True)

    @property
    def PROVIDER_NAME(self) -> str:
        """透传实际供应商身份；旧替身未声明时返回空串。"""
        return getattr(self._provider, "PROVIDER_NAME", "")

    @property
    def model_name(self) -> str:
        """透传实际型号，不从配置推导或复制可变状态。"""
        return getattr(self._provider, "model_name", "")

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        """用剩余时间限制文本请求；不足时底层 provider 不会被调用。"""
        return self._provider.complete(req, timeout_s=self._allowed())

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """用同一剩余时间限制带图判定请求。"""
        return self._provider.describe(req, timeout_s=self._allowed())

    def config(self) -> dict[str, str]:
        """透传模型配置，同时记录本适配器的整个请求等待上限。"""
        return {**self._provider.config(), "request_timeout_s": str(self._limit_s)}

    def _allowed(self) -> float:
        """生产无总时长限制时，只执行链路自己的单请求上限。"""
        if self._deadline is None:
            return self._limit_s
        return self._deadline.allowed(self._limit_s, self._source)
