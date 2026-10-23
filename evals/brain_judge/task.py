"""judge：生产成功判定器读取冻结真值，独立计算 TP/FP/FN/TN。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_judge.quality import judge_quality
from evals.brain_judge.scorer import judge_scorer
from evals.brain_judge.solver import judge_solver
from evals.dataset.brain_judge import load
from evals.runconfig import load_config, resolve_grader
from pokemon_agent.env import load_env_file


@task
def brain_judge(
    version: str = "v20261020_1846", judge_model: str | None = None, grader_model: str = "none"
) -> Task:
    """用独立真值历史测成功判定；目标和历史通过生产信封交给模型。"""
    load_env_file()
    cases = load(version)
    configuration = load_config()
    model = judge_model or str(configuration["models"]["judge_model"])
    grader = (
        None
        if grader_model is None or grader_model.lower() == "none"
        else resolve_grader(configuration["evaluation_models"], grader_model)
    )
    return Task(
        dataset=[
            Sample(
                id=c.case_id,
                input=c.request.goal.goal,
                metadata={"case": c.model_dump(mode="json")},
            )
            for c in cases
        ],
        solver=judge_solver(model),
        scorer=[judge_scorer(), judge_quality(grader)],
        model="none",
        fail_on_error=False,
    )
