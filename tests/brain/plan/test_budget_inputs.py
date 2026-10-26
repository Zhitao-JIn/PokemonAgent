"""Planning budgets carry an amount from the model and a unit fixed by the capability."""

import json

import pytest
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import AttemptFailed
from pokemon_agent.brain.interface import DecomposeResult, PlanResult


def invoke(brain: Brain, capability: str) -> PlanResult | DecomposeResult:
    """Call the public planning capability without changing its typed result contract."""
    if capability == "plan":
        return brain.plan(prompt="p", goal_stack=["g"], history=[], max_push=2)
    return brain.decompose(prompt="p", goal="g", context=[], max_tasks=2)


def reply(budget: object) -> str:
    """One complete proposal with the budget supplied by the test."""
    return json.dumps(
        {"new_items": [{"goal": "g", "success_criteria": "c", "budget": budget}], "why": "evidence"}
    )


@pytest.mark.parametrize(("capability", "unit"), [("plan", "tasks"), ("decompose", "actions")])
@pytest.mark.parametrize("amount", [1, 2, 12])
def test_scalar_budget_gets_its_fixed_unit_without_another_model_call(
    capability: str, unit: str, amount: int
) -> None:
    raw = reply(amount)
    provider = ScriptedLLM(text_reply(raw))

    result = invoke(Brain(plan_llm=provider), capability)

    proposal = result.plan if isinstance(result, PlanResult) else result.decomposition
    assert proposal.new_items[0].budget.model_dump() == {"limit": amount, "unit": unit}
    assert result.calls[0].payload["raw"] == raw
    assert result.calls[0].payload["ok"] == "true"
    assert unit in result.calls[0].payload["normalizations"][0]
    assert len(provider.requests) == len(result.calls) == 1


@pytest.mark.parametrize("capability", ["plan", "decompose"])
@pytest.mark.parametrize("budget", [0, -1, True, False, 2.5, "2", None, [], {}])
def test_invalid_scalar_budgets_are_not_guessed_or_repaired(
    capability: str, budget: object
) -> None:
    provider = ScriptedLLM(text_reply(reply(budget)))

    with pytest.raises(AttemptFailed) as caught:
        invoke(Brain(plan_llm=provider), capability)

    assert caught.value.call.error_kind == "ParseFailure"
    assert caught.value.call.payload["raw"] == reply(budget)
    assert len(provider.requests) == 1


@pytest.mark.parametrize(("capability", "unit"), [("plan", "tasks"), ("decompose", "actions")])
def test_existing_explicit_budget_objects_still_work(capability: str, unit: str) -> None:
    provider = ScriptedLLM(text_reply(reply({"limit": 2, "unit": unit})))

    result = invoke(Brain(plan_llm=provider), capability)

    assert result.calls[0].payload["ok"] == "true"
    assert "normalizations" not in result.calls[0].payload


@pytest.mark.parametrize("capability", ["plan", "decompose"])
def test_an_explicit_wrong_unit_is_not_silently_overwritten(capability: str) -> None:
    provider = ScriptedLLM(text_reply(reply({"limit": 2, "unit": "episodes"})))

    with pytest.raises(AttemptFailed) as caught:
        invoke(Brain(plan_llm=provider), capability)

    assert "unit" in caught.value.call.error
