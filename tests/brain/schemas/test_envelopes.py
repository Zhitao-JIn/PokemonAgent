"""brain 的四个补全信封：必填、默认值、类型拒绝、字段集合与序列化往返。

这是对 `test_llm_complete_req_roundtrip.py`（只守 `prompt` 字段）的补全——
字段被静默删除是 0915 事故的教训，这里用 `model_dump().keys()` 把四个模型的
字段集合全部钉住，而不是只盯一个字段。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.brain import schemas
from pokemon_agent.brain.schemas import (
    LlmCompleteReq,
    LlmCompleteResp,
    VisionDescribeReq,
    VisionDescribeResp,
)


def test_the_package_exports_exactly_the_four_envelopes() -> None:
    """包出口 `__all__` 恰为四个信封名，且都能从 `pokemon_agent.brain.schemas` 取到。"""

    assert schemas.__all__ == [
        "LlmCompleteReq",
        "LlmCompleteResp",
        "VisionDescribeReq",
        "VisionDescribeResp",
    ]

    for name in schemas.__all__:
        assert getattr(schemas, name) is not None


@pytest.mark.parametrize(
    ("build", "loc", "err_type"),
    [
        (lambda: LlmCompleteReq(), "prompt", "missing"),
        (lambda: LlmCompleteResp(), "text", "missing"),
        (lambda: VisionDescribeReq(prompt="q"), "images", "missing"),
        (lambda: VisionDescribeReq(images=["a"]), "prompt", "missing"),
        (lambda: VisionDescribeResp(), "text", "missing"),
    ],
    ids=["req-prompt", "resp-text", "vision-images", "vision-prompt", "vision-resp-text"],
)
def test_a_missing_required_field_is_rejected(build: object, loc: str, err_type: str) -> None:
    """缺必填字段一律 ValidationError，且错误指向正确的字段与类型。"""

    with pytest.raises(ValidationError) as exc_info:
        build()

    errors = exc_info.value.errors()

    assert any(e["loc"] == (loc,) and e["type"] == err_type for e in errors)


def test_the_llm_request_thinking_defaults_to_none() -> None:
    """`LlmCompleteReq.thinking` 缺省为 None（沿用 provider 装配时的设置）。"""

    assert LlmCompleteReq(prompt="p").thinking is None


@pytest.mark.parametrize("thinking", [None, True, False])
def test_the_thinking_flag_is_preserved_verbatim(thinking: bool | None) -> None:
    """thinking 三态（None/True/False）原样保留。"""

    assert LlmCompleteReq(prompt="p", thinking=thinking).thinking is thinking


@pytest.mark.parametrize(
    ("model", "token_fields"),
    [
        (
            LlmCompleteResp(text="x"),
            ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens"),
        ),
        (
            VisionDescribeResp(text="x"),
            ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"),
        ),
    ],
    ids=["llm-resp", "vision-resp"],
)
def test_the_token_counters_default_to_zero(model: object, token_fields: tuple[str, ...]) -> None:
    """两个 Resp 的四个 token 数缺省都是 0。"""

    for field in token_fields:
        assert getattr(model, field) == 0


def test_the_llm_response_truncated_defaults_to_false() -> None:
    """`LlmCompleteResp.truncated` 缺省为 False——截断必须由 provider 显式给。"""

    assert LlmCompleteResp(text="x").truncated is False


@pytest.mark.parametrize(
    ("build", "loc"),
    [
        (lambda: LlmCompleteReq(prompt=None), ("prompt",)),
        (lambda: LlmCompleteReq(prompt=5), ("prompt",)),
        (lambda: VisionDescribeReq(images="abc", prompt="q"), ("images",)),
        (lambda: VisionDescribeReq(images=[1], prompt="q"), ("images", 0)),
    ],
    ids=["req-prompt-none", "req-prompt-int", "vision-images-str", "vision-images-int"],
)
def test_a_wrong_type_is_rejected(build: object, loc: tuple[object, ...]) -> None:
    """prompt 为 None 或数字被拒；images 为裸字符串或含非字符串元素被拒。"""

    with pytest.raises(ValidationError) as exc_info:
        build()

    assert any(e["loc"] == loc for e in exc_info.value.errors())


def test_the_vision_request_needs_at_least_one_image() -> None:
    """`images` 至少一张：空列表被拒。"""

    with pytest.raises(ValidationError) as exc_info:
        VisionDescribeReq(images=[], prompt="q")

    assert any(
        e["loc"] == ("images",) and e["type"] == "too_short" for e in exc_info.value.errors()
    )


def test_the_vision_request_keeps_the_image_order() -> None:
    """一张、多张都接受，且顺序保持。"""

    request = VisionDescribeReq(images=["a", "b", "c"], prompt="q")

    assert request.images == ["a", "b", "c"]


def test_an_empty_prompt_is_accepted_at_the_envelope_layer() -> None:
    """空 prompt 在信封层被接受——信封不替 provider 做内容校验（那是 describe 的事）。"""

    request = VisionDescribeReq(images=["a"], prompt="")

    assert request.prompt == ""


@pytest.mark.parametrize(
    ("model", "expected_keys"),
    [
        (LlmCompleteReq(prompt="p"), {"prompt", "thinking"}),
        (
            LlmCompleteResp(text="x"),
            {
                "text",
                "prompt_tokens",
                "completion_tokens",
                "cached_tokens",
                "reasoning_tokens",
                "truncated",
            },
        ),
        (VisionDescribeReq(images=["a"], prompt="q"), {"images", "prompt"}),
        (
            VisionDescribeResp(text="x"),
            {
                "text",
                "input_tokens",
                "output_tokens",
                "cached_tokens",
                "reasoning_tokens",
                "truncated",
            },
        ),
    ],
    ids=["llm-req", "llm-resp", "vision-req", "vision-resp"],
)
def test_the_field_set_is_exactly_the_declared_shape(
    model: object, expected_keys: set[str]
) -> None:
    """每个模型的 `model_dump()` 键恰好等于声明集合——字段被静默删除的守卫。"""

    assert set(model.model_dump().keys()) == expected_keys


@pytest.mark.parametrize(
    "model",
    [
        LlmCompleteReq(prompt="p", thinking=True),
        LlmCompleteResp(
            text="x",
            prompt_tokens=1,
            completion_tokens=2,
            cached_tokens=3,
            reasoning_tokens=4,
            truncated=True,
        ),
        VisionDescribeReq(images=["a", "b"], prompt="q"),
        VisionDescribeResp(
            text="x", input_tokens=1, output_tokens=2, cached_tokens=3, reasoning_tokens=4
        ),
    ],
    ids=["llm-req", "llm-resp", "vision-req", "vision-resp"],
)
def test_a_model_round_trips_through_dump_and_json(model: object) -> None:
    """每个模型经 `model_dump`/`model_validate` 与 JSON 序列化往返后相等。"""

    cls = type(model)

    assert cls.model_validate(model.model_dump()) == model
    assert cls.model_validate_json(model.model_dump_json()) == model
