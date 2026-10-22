"""评分只修格式：原素材保留、所有尝试留痕、低分和未知不挑答案。"""

import asyncio
from types import SimpleNamespace

import pytest
from inspect_ai.model import ChatMessageSystem, ChatMessageUser
from inspect_ai.scorer import NOANSWER
from pydantic import BaseModel, ConfigDict

from evals.common.review_generation import generate_review


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: float | None


class Grader:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.messages = []

    async def generate(self, messages):
        self.messages.append(list(messages))
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(completion=output)


def value(review):
    return NOANSWER if review.score is None else review.score


def test_format_correction_keeps_source_and_candidate_and_records_both_outputs():
    grader = Grader('{"score":0,"extra":"invalid"}', '{"score":0}')
    original = [ChatMessageSystem(content="rules"), ChatMessageUser(content="source and candidate")]

    result = asyncio.run(generate_review(grader, original, Review, value))

    assert result.value == 0
    assert len(result.attempts) == 2
    assert result.attempts[0].error
    assert not result.attempts[1].error
    assert grader.messages[0] == original
    assert grader.messages[1][:2] == original
    assert grader.messages[1][2].content == result.attempts[0].raw
    assert "JSON Schema" in grader.messages[1][3].content
    assert len(original) == 2


@pytest.mark.parametrize("raw", ['{"score":0}', '{"score":null}'])
def test_valid_low_or_unknown_score_never_gets_another_attempt(raw):
    grader = Grader(raw)

    result = asyncio.run(generate_review(grader, [], Review, value))

    assert result.review is not None
    assert len(grader.messages) == len(result.attempts) == 1


def test_format_exhaustion_keeps_every_error_and_remains_unscored():
    grader = Grader("not json", '{"extra":1}')

    result = asyncio.run(generate_review(grader, [], Review, value, max_attempts=2))

    assert result.review is None and result.value is None
    assert len(result.attempts) == 2
    assert all(attempt.error for attempt in result.attempts)


def test_transport_error_is_not_retried_as_an_invalid_review():
    grader = Grader(OSError("transport failure"))

    with pytest.raises(OSError, match="transport failure"):
        asyncio.run(generate_review(grader, [], Review, value))

    assert len(grader.messages) == 1


def test_format_attempt_budget_is_loaded_from_settings_overlay(tmp_path, monkeypatch):
    from evals.common import review_generation
    from pokemon_agent.settings import load_config

    overlay = tmp_path / "grader.json"
    overlay.write_text('{"retry":{"eval_grader_format_attempts":1}}', encoding="utf-8")
    resolved = load_config(overlay)
    assert load_config().config.retry.eval_grader_format_attempts == 2
    monkeypatch.setattr(review_generation, "load_config", lambda: resolved)
    grader = Grader("invalid", '{"score":1}')

    result = asyncio.run(generate_review(grader, [], Review, value))

    assert result.review is None
    assert len(result.attempts) == len(grader.messages) == 1
