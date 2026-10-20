"""choose 的 Inspect 主入口：多种合理动作和失败恢复由 AI 给0..1分。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_choose.dataset import load
from evals.brain_choose.inspect_scorer import contract_scorer, quality_scorer
from evals.brain_choose.inspect_solver import choose_solver
from evals.runconfig import load_config
from pokemon_agent.env import load_env_file


@task
def brain_choose(
    version: str = "v4", model: str | None = None, grader_model: str | None = None
) -> Task:
    """建议参考只供独立 grader；旧 DeepEval 动作命中诊断保留在模块 CLI。"""
    load_env_file()
    configuration = load_config()
    model = model or str(configuration["models"]["text_model"])
    grader_model = grader_model or str(configuration["evaluation_models"]["test_text"])
    cases = load(version)
    return Task(
        dataset=[
            Sample(
                id=case.case_id,
                input=case.request.goals[-1].goal,
                metadata={"case": case.model_dump(mode="json")},
            )
            for case in cases
        ],
        solver=choose_solver(model),
        scorer=[contract_scorer(), quality_scorer(grader_model)],
        model="none",
        fail_on_error=False,
        metadata={
            "capability": "choose",
            "dataset_version": version,
            "tested_model": model,
            "grader_model": grader_model,
        },
    )
