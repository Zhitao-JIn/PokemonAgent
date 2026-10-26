"""`Brain.choose` 成功路径的后置条件与「一次尝试 = 一条账」的契约。

守的是成功路径的承诺——恰好一条账、账的键集合与 token 写法、prompt 原样到达
provider、大脑自己不重试、没配 decide provider 就调被入口 assert 拦下。
"""

from __future__ import annotations

import pytest
from _doubles.brain_choose import KEYS, PROMPT, SCRIPTS
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import DecisionAttemptFailed
from pokemon_agent.brain.schemas import LlmCompleteReq


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    provider = ScriptedLLM(text_reply('{"action": "up"}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert len(result.calls) == 1


def test_the_ledger_carries_prompt_raw_and_token_counts_as_strings() -> None:
    provider = ScriptedLLM(text_reply('{"action": "up"}'))
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    call = result.calls[0]
    payload = call.payload
    assert set(payload) == {
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "ok",
        "raw",
        "prompt",
        "images",
        "started_at",
        "ended_at",
    }
    assert payload["input_tokens"] == "11"
    assert payload["output_tokens"] == "7"
    assert payload["cached_tokens"] == "3"
    assert payload["reasoning_tokens"] == "2"
    assert payload["ok"] == "true"
    assert payload["raw"] == '{"action": "up"}'
    assert payload["prompt"] == PROMPT
    assert payload["images"] == []
    assert isinstance(payload["started_at"], float)
    assert isinstance(payload["ended_at"], float)
    assert payload["started_at"] <= payload["ended_at"]
    assert call.error_kind == ""
    assert call.error == ""


def test_the_prompt_reaches_the_provider_verbatim() -> None:
    provider = ScriptedLLM(text_reply('{"action": "up"}'))
    brain = Brain(decide_llm=provider)

    brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]


def test_choose_never_retries_by_itself() -> None:
    provider = ScriptedLLM(text_reply("nonsense"))
    brain = Brain(decide_llm=provider)

    with pytest.raises(DecisionAttemptFailed):
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert len(provider.requests) == 1


def test_calling_choose_without_a_decide_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="decide provider"):
        brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)
