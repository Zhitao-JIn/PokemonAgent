"""建议不构成答案白名单；合理纠偏与等价方案能获得完整 AI 质量分。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai import eval
from inspect_ai.model import ChatMessage
from inspect_ai.scorer import NOANSWER, SampleScore, Score
from pydantic import ValidationError

from evals.brain_choose.dataset import load as choose
from evals.brain_plan.dataset import load as plan
from evals.common import advisory_quality
from evals.common.advisory_quality import AdvisoryGrade, DimensionGrade, grade_value
from evals.common.quality_metrics import quality_count, quality_mean
from evals.dataset.brain_annotations.loader import load as annotations
from evals.dataset.brain_calls.dataset_contract import ReferenceCase
from pokemon_agent.brain.interface import Action
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    ModelCall,
)


def test_recoverable_failures_are_scored_without_an_exhaustive_action_whitelist() -> None:
    rows = choose("v4")
    indexed = {row.case_id: row for row in rows}

    assert len(rows) == 206
    assert "knowledge_battle_action_menu.task.choose.000003" not in indexed
    assert "knowledge_battle_action_menu.task.choose.000009" in indexed
    assert "knowledge_pokemon_center_heal.task.choose.000001" in indexed
    for case in rows:
        assert case.reference.constraints["reference_role"] == "non_exhaustive_suggestions"
        assert "acceptable" not in case.reference.constraints
        assert case.reference.achieved is None


def test_plans_are_advisory_and_conflicting_goal_can_be_explained() -> None:
    cases = plan("v3")
    case = next(
        row for row in cases if row.case_id == "knowledge_battle_action_menu.run.plan.000002"
    )

    assert len(cases) == 26
    assert "why/note" in case.reference.constraints["advisory_examples"][0]
    assert "scenario_milestones_if_required_and_not_satisfied" not in case.reference.constraints


def test_recovery_examples_include_multiple_valid_candidates() -> None:
    rows = {row.case_id: row for row in annotations("choose", "v2")}
    case = rows["knowledge_shop_interaction.task.choose.000005"]

    assert {item.key for item in case.acceptable} == {"left", "down"}
    assert case.evaluation_mode == "advisory"
    assert case.criteria and case.suggestions


def test_ai_dimensions_give_partial_credit_instead_of_all_or_nothing() -> None:
    reference = choose("v4")[0].reference
    grade = AdvisoryGrade(
        criteria=[
            DimensionGrade(name=item.name, score=value, evidence="input proof")
            for item, value in zip(reference.criteria, [1.0, 0.5, 0.0], strict=True)
        ]
    )

    assert grade_value(reference, grade) == 0.5
    grade.criteria[1].score = None
    assert grade_value(reference, grade) == NOANSWER


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), True])
def test_invalid_numeric_scores_cannot_enter_the_mean(value: object) -> None:
    with pytest.raises(ValidationError):
        DimensionGrade(name="progress", score=value, evidence="proof")


def test_quality_metrics_preserve_zero_and_exclude_unknown_scores() -> None:
    scores = [SampleScore(score=Score(value=value)) for value in [1.0, 0.5, 0.0, NOANSWER]]

    assert quality_mean()(scores) == 0.5
    assert quality_count()(scores) == 3


def test_missing_dimensions_are_unscored_instead_of_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = choose("v4")[0]

    class Grader:
        async def generate(self, messages: list[ChatMessage]) -> SimpleNamespace:
            return SimpleNamespace(completion='{"criteria": []}')

    monkeypatch.setattr(advisory_quality, "get_model", lambda model: Grader())

    score = asyncio.run(
        advisory_quality.assess(
            "fake",
            case.reference,
            Action.model_validate({"sequence": [{"name": "right", "times": 1}]}),
            [ModelCall(payload={"prompt": "actual context"})],
        )
    )

    assert score.value == NOANSWER


def test_unlisted_recovery_action_gets_ai_score_without_leaking_reference_to_chooser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.brain_choose import inspect_solver, task

    case = next(
        row
        for row in choose("v4")
        if row.case_id == "knowledge_shop_interaction.task.choose.000046"
    )
    action = Action.model_validate({"sequence": [{"name": "right", "times": 1}]})
    assert case.request.space.enabled("right")
    assert all(
        item.get("key") != "right" for item in case.reference.constraints["suggested_actions"]
    )
    requests, messages_seen = [], []

    def invoke(
        request: FromHarnessToBrainToolChooseOnceReq,
    ) -> FromHarnessToBrainToolChooseOnceResp:
        requests.append(request)
        return FromHarnessToBrainToolChooseOnceResp(
            action=action,
            calls=[ModelCall(payload={"prompt": "actual original choose context", "images": []})],
        )

    monkeypatch.setattr(task, "load", lambda version: [case])
    monkeypatch.setattr(
        inspect_solver,
        "single_link_brain",
        lambda link, model: SimpleNamespace(chooser=SimpleNamespace(choose=invoke)),
    )
    monkeypatch.setattr(
        advisory_quality, "get_model", lambda model: RecoveryGrader(case.reference, messages_seen)
    )

    log = eval(
        task.brain_choose(model="fake", grader_model="fake-grader"),
        log_dir=str(tmp_path),
        display="none",
    )[0]

    assert log.status == "success"
    assert requests[0].model_dump() == case.request.model_dump()
    assert "reference" not in type(requests[0]).model_fields
    assert log.results.scores[1].metrics["quality_mean"].value == 1.0
    assert log.results.scores[1].metrics["quality_count"].value == 1
    assert "actual original choose context" in messages_seen[1].content[0].text


class RecoveryGrader:
    """独立假评分员接受未列入建议但合理的动作，验证接线不使用集合门禁。"""

    def __init__(self, reference: ReferenceCase, messages_seen: list[ChatMessage]) -> None:
        self.reference = reference
        self.messages_seen = messages_seen

    async def generate(self, messages: list[ChatMessage]) -> SimpleNamespace:
        self.messages_seen.extend(messages)
        return SimpleNamespace(
            completion=json.dumps(
                {
                    "criteria": [
                        {
                            "name": item.name,
                            "score": 1.0,
                            "evidence": "东侧可走，向东绕开北侧人物，调查其他合法交互站位。",
                        }
                        for item in self.reference.criteria
                    ]
                }
            )
        )


def test_choose_module_launcher_also_runs_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals.brain_choose import __main__ as launcher

    calls = []
    monkeypatch.setattr(launcher.subprocess, "call", lambda command: calls.append(command) or 0)

    assert launcher.main(["-T", "grader_model=fake"]) == 0
    assert calls[0][1:4] == ["-m", "inspect_ai", "eval"]
    assert calls[0][-2:] == ["-T", "grader_model=fake"]
