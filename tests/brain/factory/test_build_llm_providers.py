"""`build_llm_providers`：从 `BrainLlmConfig` 造出 `Brain` 要的四个 provider。

四个位置（decide/judge/verify/plan）各带一份 `LinkSpec`（型号、温度、输出上限、超时、
思考开关），型号名按前缀选厂商类，位置间可任意混搭；这些值全由调用方给出，brain 里不
写死任何数字。本文件不碰私有属性：配置经 `config()` 读，超时经手写假 `urlopen` 观察。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain import BrainLlmConfig, LinkSpec, build_llm_providers
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


def _spec(
    model: str = "qwen3.8-max",
    *,
    temperature: float = 0.0,
    max_tokens: int = 25600,
    timeout_s: float = 45,
    thinking: bool = False,
) -> LinkSpec:
    return LinkSpec(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        thinking=thinking,
    )


def test_all_positions_default_to_none() -> None:
    decide, judge, verify, plan = build_llm_providers(BrainLlmConfig())

    assert (decide, judge, verify, plan) == (None, None, None, None)


@pytest.mark.parametrize("field", ["text", "judge", "verify", "plan"])
def test_each_position_builds_only_itself(field: str) -> None:
    config = BrainLlmConfig(**{field: _spec()})

    decide, judge, verify, plan = build_llm_providers(config)

    assert sum(p is not None for p in (decide, judge, verify, plan)) == 1


def test_the_return_order_is_decide_judge_verify_plan_with_the_models_in_place() -> None:
    config = BrainLlmConfig(
        text=_spec("qwen3.8-max"),
        judge=_spec("qwen3.8-max"),
        verify=_spec("doubao-seed-1-6-250615"),
        plan=_spec("deepseek-v4-flash"),
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
    config = BrainLlmConfig(text=_spec(model))

    decide, *_ = build_llm_providers(config)

    assert decide.config()["provider"] == provider_name


def test_four_positions_with_the_same_model_still_get_distinct_instances() -> None:
    config = BrainLlmConfig(text=_spec(), judge=_spec(), verify=_spec(), plan=_spec())

    decide, judge, verify, plan = build_llm_providers(config)

    assert len({id(p) for p in (decide, judge, verify, plan)}) == 4


def test_temperature_and_max_tokens_come_from_each_positions_spec() -> None:
    config = BrainLlmConfig(
        text=_spec(temperature=0.3, max_tokens=7),
        judge=_spec(temperature=0.0, max_tokens=8),
        verify=_spec(temperature=0.1, max_tokens=9),
        plan=_spec(temperature=0.2, max_tokens=10),
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert [p.config()["temperature"] for p in (decide, judge, verify, plan)] == [
        "0.3",
        "0.0",
        "0.1",
        "0.2",
    ]
    assert [p.config()["max_tokens"] for p in (decide, judge, verify, plan)] == [
        "7",
        "8",
        "9",
        "10",
    ]


def test_single_request_timeouts_come_from_each_positions_spec(
    captured_timeouts: list[float | None],
) -> None:
    config = BrainLlmConfig(
        text=_spec(timeout_s=10),
        judge=_spec(timeout_s=45),
        verify=_spec(timeout_s=46),
        plan=_spec(timeout_s=99),
    )
    decide, judge, verify, plan = build_llm_providers(config)

    for provider in (decide, judge, verify, plan):
        provider.complete(LlmCompleteReq(prompt="hi"))

    assert captured_timeouts == [10, 45, 46, 99]


def test_thinking_is_a_per_position_switch() -> None:
    config = BrainLlmConfig(
        text=_spec(),
        judge=_spec(),
        verify=_spec(),
        plan=_spec(thinking=True),
    )

    decide, judge, verify, plan = build_llm_providers(config)

    assert [p.config()["thinking"] for p in (decide, judge, verify, plan)] == [
        "false",
        "false",
        "false",
        "true",
    ]


def test_the_vision_dump_dir_reaches_every_provider() -> None:
    config = BrainLlmConfig(text=_spec(), judge=_spec(), vision_dump_dir="dump")

    decide, judge, *_ = build_llm_providers(config)

    assert decide._vision_dump_dir == judge._vision_dump_dir == "dump"


@pytest.mark.parametrize("field", ["text", "judge", "verify", "plan"])
def test_an_unknown_model_prefix_fails_at_build_time(field: str) -> None:
    config = BrainLlmConfig(**{field: _spec("unknown-model")})

    with pytest.raises(ValueError, match="unknown-model"):
        build_llm_providers(config)
