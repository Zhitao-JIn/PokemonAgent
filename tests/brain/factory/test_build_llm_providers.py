"""`build_llm_providers`：从 `BrainLlmConfig` 造出 `Brain` 要的四个 provider。

四个位置（decide/judge/verify/plan）的型号名按前缀选厂商类，位置间可任意混搭；
温度分层（decide 0.3、其余 0.0）、输出上限分层（plan 用 plan_max_tokens）、单请求
超时分层（decide 10、其余 45、开思考 420）都写在代码常量里，改错了不报错只会悄悄
改变模型行为。本文件不碰私有属性：配置经 `config()` 读，超时经手写假 `urlopen` 观察。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain import BrainLlmConfig, build_llm_providers
from pokemon_agent.brain.schemas import LlmCompleteReq


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        reply = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}
        return json.dumps(reply).encode()


@pytest.fixture(autouse=True)
def _set_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def captured_timeouts(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    timeouts: list[float | None] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        timeouts.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return timeouts


def test_all_positions_default_to_none() -> None:
    decide, judge, verify, plan = build_llm_providers(BrainLlmConfig())

    assert (decide, judge, verify, plan) == (None, None, None, None)


@pytest.mark.parametrize("field", ["text", "judge", "verify", "plan"])
def test_each_position_builds_only_itself(field: str) -> None:
    config = BrainLlmConfig(**{field: "qwen3.8-max"})

    decide, judge, verify, plan = build_llm_providers(config)

    assert sum(p is not None for p in (decide, judge, verify, plan)) == 1


def test_the_return_order_is_decide_judge_verify_plan_with_the_models_in_place() -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="doubao-seed-1-6-250615",
        plan="deepseek-v4-flash",
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert [p.config()["model"] for p in (decide, judge, verify, plan)] == [
        "qwen3.8-max",
        "qwen3.8-max",
        "doubao-seed-1-6-250615",
        "deepseek-v4-flash",
    ]


@pytest.mark.parametrize(
    ("model", "provider_name"),
    [
        ("qwen3.8-max", "QwenProvider"),
        ("doubao-seed-1-6-250615", "ArkProvider"),
        ("deepseek-v4-flash", "DeepSeekProvider"),
    ],
)
def test_the_vendor_class_follows_the_model_prefix(model: str, provider_name: str) -> None:
    config = BrainLlmConfig(text=model)

    decide, *_ = build_llm_providers(config)

    assert decide.config()["provider"] == provider_name


def test_four_positions_with_the_same_model_still_get_distinct_instances() -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert len({id(p) for p in (decide, judge, verify, plan)}) == 4


def test_temperature_is_layered_by_position() -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert decide.config()["temperature"] == "0.3"
    assert judge.config()["temperature"] == "0.0"
    assert verify.config()["temperature"] == "0.0"
    assert plan.config()["temperature"] == "0.0"


def test_max_tokens_is_layered_with_plan_using_plan_max_tokens() -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
        max_tokens=7,
        plan_max_tokens=9,
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert decide.config()["max_tokens"] == "7"
    assert judge.config()["max_tokens"] == "7"
    assert verify.config()["max_tokens"] == "7"
    assert plan.config()["max_tokens"] == "9"


def test_max_tokens_defaults_to_25600() -> None:
    config = BrainLlmConfig(text="qwen3.8-max")

    decide, *_ = build_llm_providers(config)

    assert decide.config()["max_tokens"] == "25600"


def test_single_request_timeouts_are_layered_by_position(
    captured_timeouts: list[float | None],
) -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
    )
    decide, judge, verify, plan = build_llm_providers(config)

    decide.complete(LlmCompleteReq(prompt="hi"))
    judge.complete(LlmCompleteReq(prompt="hi"))
    verify.complete(LlmCompleteReq(prompt="hi"))
    plan.complete(LlmCompleteReq(prompt="hi"))

    assert captured_timeouts == [10, 45, 45, 45]


def test_plan_thinking_widens_only_the_plan_timeout(
    captured_timeouts: list[float | None],
) -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
        plan_thinking=True,
    )
    decide, judge, verify, plan = build_llm_providers(config)

    decide.complete(LlmCompleteReq(prompt="hi"))
    judge.complete(LlmCompleteReq(prompt="hi"))
    verify.complete(LlmCompleteReq(prompt="hi"))
    plan.complete(LlmCompleteReq(prompt="hi"))

    assert captured_timeouts == [10, 45, 45, 420]
    assert plan.config()["thinking"] == "true"


@pytest.mark.parametrize("plan_thinking", [True, False])
def test_plan_timeout_s_overrides_plan_and_leaves_others_alone(
    captured_timeouts: list[float | None], plan_thinking: bool
) -> None:
    config = BrainLlmConfig(
        text="qwen3.8-max",
        judge="qwen3.8-max",
        verify="qwen3.8-max",
        plan="qwen3.8-max",
        plan_thinking=plan_thinking,
    )
    decide, judge, verify, plan = build_llm_providers(config, plan_timeout_s=99)

    decide.complete(LlmCompleteReq(prompt="hi"))
    judge.complete(LlmCompleteReq(prompt="hi"))
    verify.complete(LlmCompleteReq(prompt="hi"))
    plan.complete(LlmCompleteReq(prompt="hi"))

    assert captured_timeouts == [10, 45, 45, 99]


@pytest.mark.parametrize("field", ["text", "judge", "verify", "plan"])
def test_an_unknown_model_prefix_fails_at_build_time(field: str) -> None:
    config = BrainLlmConfig(**{field: "gpt-4"})

    with pytest.raises(ValueError, match="gpt-4"):
        build_llm_providers(config)
