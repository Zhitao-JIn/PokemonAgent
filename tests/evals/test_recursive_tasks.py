"""递归规划二十例上的四个 Inspect 任务：用固定假端口跑完整数据集，展示分母与排除规则。"""

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai import eval

from pokemon_agent.brain.interface import Action, ActionSegment, Decomposition, RunPlan
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceResp,
    ModelCall,
)

VERSION = "v20261020_1846"
COUNTS = {"choose": 122, "judge": 183, "plan": 21, "decompose": 41}
CALLS = [ModelCall(payload={"prompt": "production context", "images": []})]


def fake_port(family: str) -> SimpleNamespace:
    """各能力一个确定性假端口：只实现被测接口，不读取任何标签。"""
    if family == "choose":
        action = Action(sequence=[ActionSegment(name="a")])
        return SimpleNamespace(
            chooser=SimpleNamespace(
                choose=lambda request: FromHarnessToBrainToolChooseOnceResp(
                    action=action, calls=CALLS
                )
            )
        )
    if family == "judge":
        return SimpleNamespace(
            judger=SimpleNamespace(
                judge=lambda request: FromHarnessToBrainToolJudgeResp(
                    decision="continue", why="目标尚未满足", calls=CALLS
                )
            )
        )
    if family == "plan":
        return SimpleNamespace(
            planner=SimpleNamespace(
                plan=lambda request: FromHarnessToBrainToolPlanOnceResp(
                    plan=RunPlan(why="现有计划已覆盖目标"), calls=CALLS
                )
            )
        )
    task = Decomposition.PlannedTask(
        goal="one", success_criteria="visible", budget={"limit": 1, "unit": "actions"}
    )
    return SimpleNamespace(
        decomposer=SimpleNamespace(
            decompose=lambda request: FromHarnessToBrainToolDecomposeResp(
                decomposition=Decomposition(why="拆成一步", new_items=[task]), calls=CALLS
            )
        )
    )


@pytest.mark.parametrize("family", list(COUNTS))
def test_each_task_runs_the_whole_recursive_dataset_with_fake_ports(
    family: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(f"evals.brain_{family}.task")
    solver_name = "inspect_solver" if family == "choose" else "solver"
    solver_module = importlib.import_module(f"evals.brain_{family}.{solver_name}")
    monkeypatch.setattr(solver_module, "single_link_brain", lambda link, model: fake_port(family))
    arguments = {"version": VERSION, "grader_model": "none"}
    task = getattr(module, f"brain_{family}")(**arguments)

    log = eval(task, log_dir=str(tmp_path), display="none")[0]

    assert log.status == "success"
    assert log.results is not None and log.results.total_samples == COUNTS[family]
    assert not [sample for sample in log.samples or [] if sample.error]


def test_the_four_tasks_default_to_the_recursive_dataset() -> None:
    for family in COUNTS:
        module = importlib.import_module(f"evals.brain_{family}.task")
        parameters = inspect.signature(getattr(module, f"brain_{family}")).parameters

        assert parameters["version"].default == VERSION


@pytest.mark.parametrize("family", ["choose", "plan", "decompose"])
def test_advisory_quality_scores_every_labelled_case_with_a_fake_grader(
    family: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Grader:
        async def generate(self, messages: list) -> SimpleNamespace:
            names = ("state_and_scope", "progress_or_recovery", "boundaries_and_history")
            body = ",".join(f'{{"name":"{n}","score":0.75,"evidence":"x"}}' for n in names)
            return SimpleNamespace(completion='{"criteria":[' + body + "]}")

    module = importlib.import_module(f"evals.brain_{family}.task")
    solver_name = "inspect_solver" if family == "choose" else "solver"
    solver_module = importlib.import_module(f"evals.brain_{family}.{solver_name}")
    monkeypatch.setattr(solver_module, "single_link_brain", lambda link, model: fake_port(family))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")
    monkeypatch.setattr("evals.common.grader_model.get_model", lambda model, **kwargs: Grader())
    task = getattr(module, f"brain_{family}")(version=VERSION, grader_model="fake-grader")

    log = eval(task, log_dir=str(tmp_path), display="none")[0]

    assert log.status == "success" and log.results is not None
    quality = next(s for s in log.results.scores if "quality_count" in s.metrics)
    assert quality.metrics["quality_count"].value == COUNTS[family]
    assert quality.metrics["quality_mean"].value == 0.75
