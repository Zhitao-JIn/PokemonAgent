"""`_load_json` 的容忍边界：从第一个 `{`/`[` 读出完整值，值外容忍、值内抛错。

这是 brain 测试里唯一直接测私有函数的地方（intent 硬边界 2 的已确认破例）：`_load_json`
是 choose / judge / verify / summarize / plan / decompose 六条解析共用的地基，它的容忍
边界本身就是契约。成功断言比较解析出的 Python 值；失败只断 `json.JSONDecodeError`，
「没有 JSON 值」那一类额外断 `msg` 含 `no JSON value`。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain.brain import _load_json


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        '```JSON\n{"a": 1}\n```',
        '```json{"a": 1}```',
        '  ```json\n{"a": 1}\n```  ',
    ],
    ids=["json-tag", "no-tag", "uppercase-tag", "no-newline", "surrounding-whitespace"],
)
def test_a_fence_with_or_without_the_json_tag_is_stripped(text: str) -> None:
    assert _load_json(text) == {"a": 1}


def test_only_the_outermost_fence_is_handled() -> None:
    text = '```json\n{"a": 1}\n``` and ```json\n{"b": 2}\n```'

    assert _load_json(text) == {"a": 1}


@pytest.mark.parametrize(
    "text",
    [
        'Sure, here it is:\n{"a": 1}',
        'say "hi" then {"a": 1}',
        'text ```json\n{"a": 1}\n```',
    ],
    ids=["prose-then-object", "quote-then-object", "prose-then-fence"],
)
def test_text_before_the_first_brace_is_skipped(text: str) -> None:
    assert _load_json(text) == {"a": 1}


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1} trailing words',
        '{"a": 1}}',
        '{"a": 1} // note',
        '{"a": 1}\n{"b": 2}',
    ],
    ids=["trailing-words", "extra-brace", "comment-after", "second-object"],
)
def test_content_after_the_value_is_ignored(text: str) -> None:
    assert _load_json(text) == {"a": 1}


def test_a_top_level_array_is_a_valid_start() -> None:
    assert _load_json("prefix [1, 2] suffix") == [1, 2]


def test_the_earlier_of_an_object_and_an_array_wins() -> None:
    assert _load_json('[{"a": 1}] {"b": 2}') == [{"a": 1}]


def test_a_nested_value_is_read_whole() -> None:
    assert _load_json('x {"a": {"b": [1, {"c": 2}]}} y') == {"a": {"b": [1, {"c": 2}]}}


def test_a_closing_brace_inside_a_string_does_not_end_the_value() -> None:
    assert _load_json('{"a": "x}"} tail') == {"a": "x}"}


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1,}',
        '{"a": 1 "b": 2}',
        '{"a": 1, // c\n "b": 2}',
        "{a: 1}",
    ],
    ids=["trailing-comma", "missing-comma", "inline-comment", "unquoted-key"],
)
def test_a_syntax_error_inside_the_value_still_raises(text: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        _load_json(text)


def test_single_quotes_still_raise() -> None:
    with pytest.raises(json.JSONDecodeError):
        _load_json("{'a': 1}")


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1',
        '{"a": [1, 2',
        '[ {"a": 1} ',
    ],
    ids=["unterminated-object", "unterminated-array-in-object", "unterminated-array"],
)
def test_a_truncated_value_still_raises(text: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        _load_json(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "just words",
        "```json\n```",
        '"just a string"',
        "123",
    ],
    ids=["empty", "whitespace-only", "words", "empty-fence", "bare-string", "number"],
)
def test_text_without_any_json_value_raises(text: str) -> None:
    with pytest.raises(json.JSONDecodeError) as excinfo:
        _load_json(text)

    assert "no JSON value" in excinfo.value.msg
