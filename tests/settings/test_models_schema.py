"""`models` 段的字段契约：thinking 可选、未知键仍拒绝、plan 的必填语义不变。"""

import pytest
from pydantic import ValidationError

from pokemon_agent.settings.schema.models import ModelLink, ModelsConfig, PlanModelLink


def test_model_link_defaults_thinking_to_false() -> None:
    link = ModelLink(model="qwen3.8-flash", temperature=0.3, max_tokens=25600, timeout_s=10)

    assert link.thinking is False
    assert link.cache_marker is None


def test_model_link_accepts_a_nonempty_cache_boundary() -> None:
    link = ModelLink(
        model="claude-haiku-5-5",
        temperature=0.0,
        max_tokens=16000,
        timeout_s=60,
        cache_marker="## 本次输入",
    )

    assert link.cache_marker == "## 本次输入"


def test_model_link_rejects_an_empty_cache_boundary() -> None:
    with pytest.raises(ValidationError, match="cache_marker"):
        ModelLink(
            model="claude-haiku-5-5",
            temperature=0.0,
            max_tokens=16000,
            timeout_s=60,
            cache_marker="",
        )


def test_model_link_accepts_explicit_thinking() -> None:
    link = ModelLink(
        model="claude-haiku-5-5",
        temperature=0.0,
        max_tokens=16000,
        timeout_s=60,
        thinking=True,
    )

    assert link.thinking is True


def test_model_link_still_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelLink(
            model="qwen3.8-flash",
            temperature=0.3,
            max_tokens=25600,
            timeout_s=10,
            unknown=True,
        )


def test_plan_link_keeps_thinking_required() -> None:
    with pytest.raises(ValidationError, match="thinking"):
        PlanModelLink(
            model="deepseek-flash",
            temperature=0.0,
            max_tokens=25600,
            timeout_s=90,
        )

    link = PlanModelLink(
        model="deepseek-flash",
        temperature=0.0,
        max_tokens=25600,
        timeout_s=90,
        thinking=True,
    )
    assert link.thinking is True


def test_models_config_accepts_mixed_thinking_links() -> None:
    config = ModelsConfig.model_validate(
        {
            "text": {
                "model": "qwen3.8-flash",
                "temperature": 0.3,
                "max_tokens": 25600,
                "timeout_s": 10,
                "thinking": False,
            },
            "judge": {
                "model": "qwen3.8-flash",
                "temperature": 0.0,
                "max_tokens": 25600,
                "timeout_s": 45,
                "thinking": False,
            },
            "verify": {
                "model": "claude-haiku-5-5",
                "temperature": 0.0,
                "max_tokens": 16000,
                "timeout_s": 60,
                "thinking": True,
            },
            "plan": {
                "model": "deepseek-flash",
                "temperature": 0.0,
                "max_tokens": 25600,
                "timeout_s": 90,
                "thinking": True,
            },
            "json_mode": True,
        }
    )

    assert [config.text.thinking, config.judge.thinking, config.verify.thinking] == [
        False,
        False,
        True,
    ]
