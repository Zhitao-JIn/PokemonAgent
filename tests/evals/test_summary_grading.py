"""摘要评分的关键边界：重大失真、未知分母、三层宏平均与实际输入可见性。"""

import asyncio
import math
from types import SimpleNamespace

import pytest
from inspect_ai.model import ChatMessage
from inspect_ai.scorer import NOANSWER, SampleScore, Score
from pydantic import ValidationError

from evals.brain_summary import grading
from evals.brain_summary.contract import DIMENSIONS, SummaryReview
from evals.brain_summary.dataset import load
from evals.brain_summary.grading import quality_value, review_pass
from evals.brain_summary.metrics import summary_quality
from evals.brain_summary.scorer import contract_checks
from pokemon_agent.brain.interface import EpisodeSummary
from pokemon_agent.schemas.harness import ModelCall


def review(value: float | None = 1.0, distortion: bool | None = False) -> SummaryReview:
    """有证据的完整评分响应；可显式构造未知或重大失真。"""
    evidence = {"source_evidence": "输入观察", "candidate_evidence": "summary", "reason": "依据"}
    return SummaryReview.model_validate(
        {
            "dimensions": [{"name": name, "score": value, **evidence} for name in DIMENSIONS],
            "major_distortion": {"present": distortion, **evidence},
        }
    )


def sample(layer: str, result: SummaryReview) -> SampleScore:
    """模拟一次合法 scorer 产物，供公开 metric 入口聚合。"""
    return SampleScore(
        score=Score(
            value=quality_value(result),
            metadata={"layer": layer, "review": result.model_dump(mode="json")},
        )
    )


def test_major_distortion_fails_review_even_when_dimension_mean_is_high() -> None:
    result = review(distortion=True)

    assert quality_value(result) == 1.0
    assert review_pass(result) == 0.0
    metrics = summary_quality()([sample(layer, result) for layer in ("task", "episode", "run")])
    assert metrics["quality_mean"] == 1.0
    assert metrics["major_distortion_rate"] == 1.0
    assert metrics["review_pass_rate"] == 0.0


def test_unknown_dimension_does_not_shrink_the_quality_denominator() -> None:
    result = review()
    result.dimensions[0].score = None

    metrics = summary_quality()([sample("task", result)])

    assert quality_value(result) == NOANSWER and review_pass(result) is None
    assert metrics["quality_n"] == 0
    assert metrics["factual_fidelity_n"] == 0
    assert metrics["key_information_n"] == 1
    assert metrics["major_distortion_n"] == 1
    assert metrics["review_pass_n"] == 0
    assert math.isnan(metrics["quality_mean"])


def test_macro_average_weights_layers_equally_and_requires_all_three() -> None:
    scores = [sample("task", review(0.0)) for _ in range(3)]
    scores += [sample("episode", review(1.0)), sample("run", review(1.0))]

    metrics = summary_quality()(scores)

    assert metrics["quality_mean"] == pytest.approx(2 / 3)
    assert metrics["sample_quality_mean"] == 0.4
    assert metrics["task_quality_n"] == 3
    assert math.isnan(summary_quality()(scores[:-1])["quality_mean"])


def test_unknown_distortion_does_not_erase_known_quality_or_count_as_a_pass() -> None:
    result = review(0.75, distortion=None)

    metrics = summary_quality()([sample("run", result)])

    assert metrics["quality_n"] == 1 and metrics["major_distortion_n"] == 0
    assert metrics["review_pass_n"] == 0


@pytest.mark.parametrize("value", [True, -0.1, 1.1, float("nan"), float("inf")])
def test_review_rejects_invalid_numeric_quality(value: object) -> None:
    raw = review().model_dump()
    raw["dimensions"][0]["score"] = value

    with pytest.raises(ValidationError):
        SummaryReview.model_validate(raw)


def test_task_markdown_is_optional_but_episode_and_run_require_it() -> None:
    answer = EpisodeSummary(
        summary="具体总结", reason="结论", quality_score=0.1, quality_rationale="原料少"
    )

    assert all(contract_checks("task", answer).values())
    assert not all(contract_checks("episode", answer).values())
    assert not all(contract_checks("run", answer).values())


@pytest.mark.parametrize("malformed", ["missing", "duplicate", "empty_evidence", "invalid_json"])
def test_malformed_grader_response_is_unscored(
    malformed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    raw = review().model_dump()
    if malformed == "missing":
        raw["dimensions"].pop()
    elif malformed == "duplicate":
        raw["dimensions"][-1] = raw["dimensions"][0]
    elif malformed == "empty_evidence":
        raw["major_distortion"]["source_evidence"] = ""
    output = "invalid" if malformed == "invalid_json" else json.dumps(raw)

    class Grader:
        async def generate(self, messages: list[ChatMessage]) -> SimpleNamespace:
            return SimpleNamespace(completion=output)

    monkeypatch.setattr(grading, "get_model", lambda model: Grader())
    case = load()[0]
    answer = EpisodeSummary(summary="s", quality_score=0.1, quality_rationale="r")
    score = asyncio.run(
        grading.assess(
            "fake", case.layer, case.reference, answer, [ModelCall(payload={"prompt": "sent"})]
        )
    )

    assert score.value == NOANSWER and "review" not in (score.metadata or {})


def test_disabled_grader_never_calls_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("disabled grader accessed a model")

    monkeypatch.setattr(grading, "get_model", unexpected)
    case = load()[0]
    answer = EpisodeSummary(summary="s", quality_score=0.1, quality_rationale="r")

    score = asyncio.run(grading.assess("none", case.layer, case.reference, answer, []))

    assert score.value == NOANSWER
