"""plan 与 decompose 独立入口：原始信封、结构约束和语义评分各自运行。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai import eval

from evals.brain_decompose.compare import contract_checks as decompose_checks
from evals.brain_decompose.dataset import load as load_decompositions
from evals.brain_plan.compare import contract_checks as plan_checks
from evals.brain_plan.dataset import load as load_plans
from pokemon_agent.brain.interface import Decomposition, RunPlan
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolPlanOnceResp,
    ModelCall,
)


def test_planning_tasks_have_their_own_frozen_inputs() -> None:
    plans, decompositions = load_plans(), load_decompositions()

    assert len(plans) == 26 and len(decompositions) == 37
    assert all(case.reference.case_id == case.case_id for case in plans + decompositions)
    assert all(case.request.run_id for case in plans)
    assert all(case.request.goal.goal for case in decompositions)


def test_plan_contract_checks_goal_indices_and_dispatchability() -> None:
    case = load_plans()[0]
    invalid = RunPlan(updates=[RunPlan.PlanUpdate(index=len(case.request.plan), status="pending")])
    no_work = RunPlan(
        updates=[
            RunPlan.PlanUpdate(index=index, status="abandoned")
            for index in range(len(case.request.plan))
        ]
    )

    assert not plan_checks(case.request, invalid)["valid_indices"]
    assert not plan_checks(case.request, no_work)["dispatchable_goal"]
    assert all(plan_checks(case.request, RunPlan()).values())


def test_decomposition_contract_enforces_the_current_request_limit() -> None:
    request = load_decompositions()[0].request.model_copy(update={"max_tasks": 1})
    task = Decomposition.PlannedTask(goal="one", success_criteria="visible", max_steps=1)

    assert all(decompose_checks(request, Decomposition(tasks=[task])).values())
    assert not decompose_checks(request, Decomposition(tasks=[task, task]))["task_limit"]


@pytest.mark.parametrize("family", ["plan", "decompose"])
def test_independent_tasks_run_production_ports_without_leaking_references(
    family: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module(f"evals.brain_{family}.task")
    original = module.load()[0]
    seen = []

    def invoke(request):
        seen.append(request)
        calls = [ModelCall(payload={"prompt": "actual production context", "images": []})]
        if family == "plan":
            return FromHarnessToBrainToolPlanOnceResp(plan=RunPlan(), calls=calls)
        task = Decomposition.PlannedTask(goal="one", success_criteria="visible", max_steps=1)
        return FromHarnessToBrainToolDecomposeResp(
            decomposition=Decomposition(tasks=[task]), calls=calls
        )

    port = SimpleNamespace(**{family: invoke})
    monkeypatch.setattr(module, "load", lambda version="v1": [original])
    solver_module = importlib.import_module(f"evals.brain_{family}.solver")
    monkeypatch.setattr(
        solver_module.BrainTool,
        "build",
        lambda **kwargs: SimpleNamespace(**{"planner" if family == "plan" else "decomposer": port}),
    )
    task = getattr(module, f"brain_{family}")(model="fake", grader_model="none")

    log = eval(task, log_dir=str(tmp_path), display="none")[0]

    assert log.status == "success"
    assert len(seen) == 1 and seen[0].model_dump() == original.request.model_dump()
    assert "reference" not in type(seen[0]).model_fields
    assert log.results.scores[0].metrics["judged_accuracy"].value == 1
    assert log.results.scores[1].metrics["quality_count"].value == 0


@pytest.mark.parametrize("family", ["plan", "decompose"])
def test_independent_dataset_rejects_a_changed_reference_fingerprint(
    family: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import json

    from evals.dataset.errors import DatasetError

    module = importlib.import_module(f"evals.brain_{family}.dataset")
    source = json.loads((module.DATASET_DIR / "v1/manifest.json").read_text("utf-8"))
    source["references_sha256"] = "0" * 64
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1/manifest.json").write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(module, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="fingerprint"):
        module.load()
