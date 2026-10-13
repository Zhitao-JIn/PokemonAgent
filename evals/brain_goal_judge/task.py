"""judge：生产成功判定器读取冻结真值，独立计算 TP/FP/FN/TN。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_goal_judge.dataset import load
from evals.brain_goal_judge.scorer import judge_scorer
from evals.brain_goal_judge.solver import judge_solver
from evals.runconfig import load_config
from pokemon_agent.env import load_env_file


@task
def brain_goal_judge(version: str = "v1", judge_model: str | None = None) -> Task:
    """用独立真值历史测成功判定；目标和历史通过生产信封交给模型。"""
    load_env_file()
    cases = load(version)
    model = judge_model or str(load_config()["models"]["judge_model"])
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
        scorer=judge_scorer(),
        model="none",
        fail_on_error=False,
    )
