"""空正文 → EmptyCompletion，tool 层原样重问（不叠纠正说明）。"""

from __future__ import annotations

import pytest

from pokemon_agent.brain.errors import EmptyCompletion
from pokemon_agent.brain.providers import _OpenAICompatibleBase


def _resp(content, finish="stop", reasoning=7):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 9,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_empty_body_raises_empty_completion(content) -> None:
    with pytest.raises(EmptyCompletion) as info:
        _OpenAICompatibleBase._unpack(_resp(content, finish="length"))
    assert info.value.reasoning_tokens == 7
    assert info.value.finish_reason == "length"


def test_non_empty_body_unpacks() -> None:
    assert _OpenAICompatibleBase._unpack(_resp("{}"))[0] == "{}"


def test_empty_completion_is_replayed_without_correction() -> None:
    from pokemon_agent.direct.brain_tool import _PARSE_ERROR_KINDS

    assert EmptyCompletion.__name__ not in _PARSE_ERROR_KINDS
