"""`Brain.choose` 的解析分支：模型怎么写，大脑怎么读。

守的是「解析」这件事——按键成单段、JSON 围栏与多余文字被容忍、脚本参数按签名收、
类型与可选参数按签名定。全部经公开方法 `choose()` 喂文本来测，不 import 私有函数。
"""

from __future__ import annotations

from _doubles.brain_choose import KEYS, PROMPT, SCRIPTS
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Action, ActionSegment, Brain, ScriptCall


def test_a_key_name_becomes_a_single_segment_with_times_one() -> None:
    provider = ScriptedLLM(text_reply('{"action": "up"}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action == Action(sequence=[ActionSegment(name="up", times=1)])
    assert result.action.script is None


def test_a_json_fence_around_the_answer_is_tolerated() -> None:
    provider = ScriptedLLM(text_reply('```json\n{"action": "up"}\n```'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action == Action(sequence=[ActionSegment(name="up", times=1)])


def test_text_around_the_json_object_is_ignored() -> None:
    provider = ScriptedLLM(text_reply('Sure, here is my move:\n{"action": "a"}\nHope that helps'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action == Action(sequence=[ActionSegment(name="a", times=1)])


def test_a_script_call_reads_args_from_the_nested_object() -> None:
    provider = ScriptedLLM(text_reply('{"action": "walk_to", "args": {"x": 5, "y": 2}}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action.script == ScriptCall(name="walk_to", args={"x": 5, "y": 2})
    assert result.action.sequence == []


def test_a_script_call_also_reads_args_flattened_at_the_top_level() -> None:
    provider = ScriptedLLM(text_reply('{"action": "walk_to", "x": 5, "y": 2}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action.script == ScriptCall(name="walk_to", args={"x": 5, "y": 2})
    assert result.action.sequence == []


def test_integer_arguments_accept_digit_strings() -> None:
    provider = ScriptedLLM(text_reply('{"action": "walk_to", "args": {"x": "5", "y": " 2 "}}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action.script == ScriptCall(name="walk_to", args={"x": 5, "y": 2})


def test_fields_outside_the_signature_are_ignored() -> None:
    provider = ScriptedLLM(text_reply('{"action": "walk_to", "x": 1, "y": 2, "thought": "hi"}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action.script == ScriptCall(name="walk_to", args={"x": 1, "y": 2})


def test_optional_script_arguments_may_be_missing_and_string_arguments_are_stripped() -> None:
    provider = ScriptedLLM(text_reply('{"action": "use_item", "item": " potion "}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action.script == ScriptCall(name="use_item", args={"item": "potion"})
    assert "quantity" not in result.action.script.args


def test_surrounding_whitespace_in_the_action_name_is_stripped() -> None:
    provider = ScriptedLLM(text_reply('{"action": "  up  "}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert result.action == Action(sequence=[ActionSegment(name="up", times=1)])
