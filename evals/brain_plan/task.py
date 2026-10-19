"""plan 独立入口：生产调用、机械约束与独立证据量表分别记分。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_plan.dataset import load
from evals.brain_plan.scorer import contract_scorer, quality_scorer
from evals.brain_plan.solver import plan_solver
from evals.runconfig import load_config
from pokemon_agent.env import load_env_file


@task
def brain_plan(
    version: str = "v2",
    model: str | None = None,
    grader_model: str | None = None,
) -> Task:
    """独立选择被测模型与量表评分模型；grader_model=none 只跑机械约束。"""
    load_env_file()
    configuration = load_config()
    model = model or str(configuration["models"]["plan_model"])
    grader_model = grader_model or str(configuration["evaluation_models"]["test_text"])
    cases = load(version)
    return Task(
        dataset=[
            Sample(
                id=case.case_id,
                input=case.request.plan[0].task.goal if case.request.plan else case.case_id,
                metadata={"case": case.model_dump(mode="json")},
            )
            for case in cases
        ],
        solver=plan_solver(model),
        scorer=[contract_scorer(), quality_scorer(grader_model)],
        model="none",
        fail_on_error=False,
        metadata={
            "capability": "plan",
            "dataset_version": version,
            "tested_model": model,
            "grader_model": grader_model,
        },
    )
