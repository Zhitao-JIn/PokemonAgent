"""独立量表评分保留未知与失败，不能省略条目或把候选自述当证据。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from inspect_ai.scorer import NOANSWER

from evals.brain_plan.dataset import load
from evals.common import source_quality
from evals.common.source_quality import CriterionGrade, QualityGrade, grade_value
from pokemon_agent.brain.interface import RunPlan
from pokemon_agent.schemas.harness import ModelCall


@pytest.mark.parametrize(
    ("marks", "expected"),
    [
        ([True, True, True, True], "C"),
        ([True, None, True, True], NOANSWER),
        ([False, None, True, True], "I"),
    ],
)
def test_mandatory_rubric_results_distinguish_pass_fail_and_unknown(marks, expected) -> None:
    reference = load()[0].reference
    grade = QualityGrade(
        criteria=[
            CriterionGrade(name=item.name, met=mark, evidence="source proof")
            for item, mark in zip(reference.criteria, marks, strict=True)
        ]
    )

    assert grade_value(reference, grade) == expected


def test_missing_or_duplicate_rubric_items_are_not_valid_scores() -> None:
    reference = load()[0].reference
    item = CriterionGrade(name=reference.criteria[0].name, met=True, evidence="source")

    with pytest.raises(ValueError, match="match"):
        grade_value(reference, QualityGrade(criteria=[item] * len(reference.criteria)))


def test_semantic_grader_gets_actual_context_images_candidate_and_separate_reference(
    monkeypatch,
) -> None:
    case = load()[0]
    seen = []
    image = "data:image/png;base64,AA=="
    calls = [ModelCall(payload={"prompt": "actual original context", "images": [image]})]

    class Grader:
        async def generate(self, messages):
            seen.extend(messages)
            return SimpleNamespace(
                completion=json.dumps(
                    {
                        "criteria": [
                            {"name": item.name, "met": True, "evidence": "visible request evidence"}
                            for item in case.reference.criteria
                        ]
                    }
                )
            )

    monkeypatch.setattr(source_quality, "get_model", lambda model: Grader())

    score = asyncio.run(source_quality.assess("fake-grader", case.reference, RunPlan(), calls))

    assert score.value == "C" and score.metadata["truth_method"] == "model_review"
    assert "actual original context" in seen[1].content[0].text
    assert "baseline_file" not in seen[1].content[0].text
    assert seen[1].content[1].image == image


def test_invalid_model_grade_is_unjudged_instead_of_a_success(monkeypatch) -> None:
    case = load()[0]

    class Grader:
        async def generate(self, messages):
            return SimpleNamespace(completion='{"criteria": []}')

    monkeypatch.setattr(source_quality, "get_model", lambda model: Grader())

    score = asyncio.run(
        source_quality.assess(
            "fake-grader", case.reference, RunPlan(), [ModelCall(payload={"prompt": "context"})]
        )
    )

    assert score.value == NOANSWER
