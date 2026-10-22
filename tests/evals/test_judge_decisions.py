"""完整决策与二元成功投影分别计分，防止把旧 false 猜成 continue。"""

import math

import pytest
from pydantic import ValidationError

from evals.brain_judge.decision_metrics import summarize_decisions
from evals.dataset.brain_judge.schemas import JudgeCase
from pokemon_agent.brain import Goal
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


def test_blocked_and_continue_are_distinct_even_when_both_are_unsuccessful() -> None:
    result = summarize_decisions([("blocked", "continue"), ("continue", "continue")])

    assert result["decision_n"] == 2 and result["decision_accuracy"] == 0.5
    assert result["decision_blocked_to_continue"] == 1
    assert result["decision_blocked_accuracy"] == 0
    assert result["decision_continue_accuracy"] == 1


def test_a_binary_label_does_not_supply_a_full_decision_label() -> None:
    case = JudgeCase(
        case_id="old",
        request=FromHarnessToBrainToolJudgeReq(goal=Goal(goal="g", criteria="c")),
        achieved=False,
    )

    assert case.expected_decision is None
    assert summarize_decisions([])["decision_n"] == 0
    assert math.isnan(summarize_decisions([])["decision_accuracy"])


def test_full_decision_labels_cannot_conflict_with_success_projection() -> None:
    with pytest.raises(ValidationError, match="conflicts"):
        JudgeCase(
            case_id="invalid",
            request=FromHarnessToBrainToolJudgeReq(goal=Goal(goal="g", criteria="c")),
            achieved=True,
            expected_decision="blocked",
        )
