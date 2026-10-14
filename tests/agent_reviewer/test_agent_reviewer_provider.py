"""A2 provider：fake provider 确认 `describe` 收 `(prompt, [frame])`、`complete` 收 `prompt`；
异常被吞、返回空 `ProposedAnswer`。且不 import `brain`。"""

from __future__ import annotations

import pytest

from pokemon_agent.agent_reviewer import provider as ap
from pokemon_agent.agent_reviewer.provider import (
    DeepSeekProvider,
    EmptyCompletion,
    ImageNotDelivered,
    LlmResult,
    ProviderRejected,
    ToolTimeout,
    build_deepseek,
)


def test_provider_defines_local_symbols() -> None:
    # 副本自带异常与结果类型，不依赖 brain.errors。
    assert {
        EmptyCompletion,
        ImageNotDelivered,
        ProviderRejected,
        ToolTimeout,
        LlmResult,
        DeepSeekProvider,
    }
    assert "pokemon_agent.brain" not in ap.__name__


class FakeLLM:
    """不联网的 provider 替身：记录调用形参，按设定返回 / 抛错。"""

    def __init__(
        self,
        result: LlmResult | None = None,
        raise_cls: type[Exception] | None = None,
    ) -> None:
        self.result = result or LlmResult("ok", 1, 1, 0, 0)
        self.raise_cls = raise_cls
        self.complete_prompt: str | None = None
        self.describe_prompt: str | None = None
        self.describe_images: list[str] | None = None

    def complete(self, prompt: str) -> LlmResult:
        if self.raise_cls:
            raise self.raise_cls("boom")
        self.complete_prompt = prompt
        return self.result

    def describe(self, prompt: str, images: list[str]) -> LlmResult:
        if self.raise_cls:
            raise self.raise_cls("boom")
        self.describe_prompt = prompt
        self.describe_images = images
        return self.result


def test_describe_receives_prompt_and_images() -> None:
    fake = FakeLLM()
    from pokemon_agent.agent_reviewer.agent import AgentReviewer

    agent = AgentReviewer(llm=fake)
    ask = _audit_ask()
    agent.seed(ask, frame="data:image/png;base64,AAA")
    assert fake.describe_prompt is not None
    assert fake.describe_images == ["data:image/png;base64,AAA"]


def test_complete_called_without_frame() -> None:
    fake = FakeLLM()
    from pokemon_agent.agent_reviewer.agent import AgentReviewer

    agent = AgentReviewer(llm=fake)
    agent.seed(_inject_ask(), frame=None)
    assert fake.complete_prompt is not None
    assert fake.describe_images is None


@pytest.mark.parametrize(
    "exc",
    [
        EmptyCompletion(0, 0, ""),
        ImageNotDelivered(0, 100),
        ProviderRejected("x"),
        ToolTimeout("x"),
    ],
)
def test_provider_errors_swallowed_to_empty(exc: Exception) -> None:
    from pokemon_agent.agent_reviewer.agent import AgentReviewer

    # 直接以真实异常实例驱动，验证 agent 吞异常 → 空提案。
    agent = AgentReviewer(llm=_RaisingLLM(exc))
    prop = agent.seed(_inject_ask(), frame=None)
    assert prop.text is None and prop.verdict is None


class _RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def complete(self, prompt: str):
        raise self.exc

    def describe(self, prompt: str, images: list[str]):
        raise self.exc


def test_build_deepseek_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        build_deepseek("deepseek-flash", temperature=0)


def _audit_ask():
    from pokemon_agent.schemas.review_backend.communication import (
        FromReviewBackendToFrontendAskReq as _ask_mod,
    )

    return _ask_mod.FromReviewBackendToFrontendAskReq(
        seq=1, run_id="r", kind="audit", prompt="p", body="b", deadline=None
    )


def _inject_ask():
    from pokemon_agent.schemas.review_backend.communication import (
        FromReviewBackendToFrontendAskReq as _ask_mod,
    )

    return _ask_mod.FromReviewBackendToFrontendAskReq(
        seq=1, run_id="r", kind="inject", prompt="p", body="b", deadline=None
    )
