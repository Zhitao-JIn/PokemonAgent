"""`Brain.choose` 的失败分类：每类失败都有名字、带账、不吞。

守的是「失败」这件事——幻觉动作、解析不出、缺参数、类型错、截断、provider 调不通，
一律抛 `DecisionAttemptFailed` 且带这一次的账；错误看 `call.error_kind`（replay 按它归类），
不断言整句报错文本。
"""

from __future__ import annotations

import json

import pytest
from _doubles.brain_choose import KEYS, PROMPT, SCRIPTS
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import DecisionAttemptFailed, ToolTimeout


def test_an_action_outside_the_space_fails_as_illegal_action() -> None:
    provider = ScriptedLLM(text_reply('{"action": "start"}'))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "IllegalAction"
    assert "start" in excinfo.value.call.error
    assert "up" in excinfo.value.call.error
    assert "walk_to" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


def test_non_json_output_fails_as_parse_failure() -> None:
    provider = ScriptedLLM(text_reply("I think we should go up"))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert "not valid json" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


def test_a_top_level_array_fails_as_parse_failure() -> None:
    provider = ScriptedLLM(text_reply('["up"]'))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert "top level is not an object" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("reply", ['{"action": ""}', '{"action": "  "}', "{}", '{"action": 3}'])
def test_a_missing_or_empty_action_name_fails_as_parse_failure(reply: str) -> None:
    provider = ScriptedLLM(text_reply(reply))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert "non-empty string" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


def test_a_script_missing_a_required_argument_fails_as_parse_failure() -> None:
    provider = ScriptedLLM(text_reply('{"action": "walk_to", "x": 1}'))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert "missing argument 'y'" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("x", ["five", 1.5, True, []])
def test_a_wrongly_typed_int_argument_fails_as_parse_failure(x: object) -> None:
    reply = json.dumps({"action": "walk_to", "x": x, "y": 2})
    provider = ScriptedLLM(text_reply(reply))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert "must be an integer" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("reply", ['{"action": "up"}', '{"action": "u'])
def test_a_truncated_completion_fails_as_truncated_even_if_it_would_not_parse(reply: str) -> None:
    provider = ScriptedLLM(text_reply(reply, truncated=True))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "OutputTruncated"
    assert "7" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    provider = ScriptedLLM(timeout)
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert "gateway down" in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"
    assert excinfo.value.__cause__ is timeout
    assert excinfo.value.source == "choose"
    assert set(excinfo.value.call.payload) == {"ok", "prompt", "images", "started_at", "ended_at"}
    assert excinfo.value.call.payload["prompt"] == PROMPT
    assert excinfo.value.call.payload["images"] == []


def test_a_failed_attempt_still_records_tokens_and_raw_text() -> None:
    provider = ScriptedLLM(text_reply("nonsense"))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed) as excinfo:
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    payload = excinfo.value.call.payload
    assert excinfo.value.call.error_kind == "ParseFailure"
    assert payload["raw"] == "nonsense"
    assert payload["input_tokens"] == "11"
    assert payload["output_tokens"] == "7"
    assert payload["cached_tokens"] == "3"
    assert payload["reasoning_tokens"] == "2"
    assert payload["prompt"] == PROMPT
    assert payload["ok"] == "false"
