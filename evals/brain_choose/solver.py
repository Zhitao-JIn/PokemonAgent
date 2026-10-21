"""生产 chooser 单次评测；模型输出失败计分，提供者不可达由入口排除。"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from evals.dataset.brain_choose import ChooseCase
from pokemon_agent.brain.interface import Action
from pokemon_agent.direct.interface import ChoosePort
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import ModelCall


class ChooseRun(BaseModel):
    """一次现场的结果与全部调用账；action 和非空 failure 恰好取一。"""

    action: Action | None = None
    failure: str = ""
    calls: list[ModelCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> ChooseRun:
        """拒绝缺失或相互矛盾的结果，避免成功与失败同时进入指标。"""
        if (self.action is not None) == bool(self.failure):
            raise ValueError("action 与 failure 必须恰好一个有值")
        return self


class ProviderUnreachable(Exception):
    """提供者未调通的现场；保留调用账，但不产生 ChooseRun、不进入指标分母。"""

    def __init__(self, reason: str, calls: list[ModelCall]) -> None:
        """接收生产异常摘要和已有调用账，不额外发请求。"""
        super().__init__(reason)
        self.calls = list(calls)


def choose_case(case: ChooseCase, chooser: ChoosePort) -> ChooseRun:
    """仅把原始 request 交给 chooser；解析耗尽有结果，网络失败抛 ProviderUnreachable。

    调用方注入满足 ChoosePort 的对象；未知异常原样上抛。失败账有 error 时依据
    error_kind 区分模型输出错误与提供者错误；成功前已恢复的重试保留在调用账中。
    """
    try:
        response = chooser.choose(case.request)
    except MaxRetriesExceeded as error:
        output_errors = {"ParseFailure", "IllegalAction", "OutputTruncated", "EmptyCompletion"}
        if any(call.error and call.error_kind not in output_errors for call in error.calls):
            raise ProviderUnreachable(str(error), error.calls) from error
        return ChooseRun(failure=str(error), calls=error.calls)
    return ChooseRun(action=response.action, calls=response.calls)
