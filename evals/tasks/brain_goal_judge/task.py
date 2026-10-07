"""judge：生产成功判定器读取冻结真值，独立计算 TP/FP/FN/TN。"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.runconfig import load_config
from evals.scorers.brain_goal_judge import judge_scorer
from evals.solvers.brain_goal_judge import JudgeCase, judge_solver
from pokemon_agent.env import load_env_file

DATASET = Path(__file__).resolve().parents[2] / "data" / "brain_goal_judge" / "dataset.jsonl"


@task
def brain_goal_judge(dataset: str = str(DATASET), judge_model: str | None = None) -> Task:
    """用独立真值历史测成功判定；目标和历史通过生产信封交给模型。"""
    load_env_file()
    cases = [
        JudgeCase.model_validate_json(line)
        for line in Path(dataset).read_text(encoding="utf-8").splitlines()
        if line
    ]
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
