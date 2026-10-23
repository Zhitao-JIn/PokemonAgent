"""decompose 独立入口：生产调用、机械约束与独立证据量表分别记分。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_decompose.dataset import load
from evals.brain_decompose.scorer import contract_scorer, quality_scorer
from evals.brain_decompose.solver import decompose_solver
from evals.runconfig import load_config, resolve_grader
from pokemon_agent.env import load_env_file


@task
def brain_decompose(
    version: str = "v20261020_1846",
    model: str | None = None,
    grader_model: str | None = None,
) -> Task:
    """独立选择被测模型与量表评分模型；grader_model=none 只跑机械约束。"""
    load_env_file()
    configuration = load_config()
    model = model or str(configuration["models"]["plan_model"])
    grader = resolve_grader(configuration["evaluation_models"], grader_model)
    cases = load(version)
    return Task(
        dataset=[
            Sample(
                id=case.case_id,
                input=case.request.goal.goal,
                metadata={"case": case.model_dump(mode="json")},
            )
            for case in cases
        ],
        solver=decompose_solver(model),
        scorer=[contract_scorer(), quality_scorer(grader)],
        model="none",
        fail_on_error=False,
        metadata={
            "capability": "decompose",
            "dataset_version": version,
            "tested_model": model,
            "grader_model": grader.model if grader is not None else "none",
        },
    )
