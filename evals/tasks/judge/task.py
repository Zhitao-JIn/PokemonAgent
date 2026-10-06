"""judge：生产成功判定器读取冻结真值，独立计算 TP/FP/FN/TN。"""

import asyncio
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from evals.runconfig import load_config
from evals.tasks.judge.metrics import confusion_count
from evals.tasks.judge.schemas import JudgeCase, JudgeRecord
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.env import load_env_file

DATASET = Path(__file__).with_name("dataset.jsonl")


def confusion(predicted: bool, achieved: bool) -> dict[str, int]:
    """一条样本只落入一个格；标签真值永不从模型文字反推。"""
    cell = ("TP" if achieved else "FP") if predicted else ("FN" if achieved else "TN")
    return {name: int(name == cell) for name in ("TP", "FP", "FN", "TN")}


@solver
def judge_solver(model: str) -> Solver:
    """生产 Judger 消费信封；网络或重试耗尽上抛为 sample error。"""
    judger = BrainTool.build(judge=model).judger

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = JudgeCase.model_validate(state.metadata["case"])
        response = await asyncio.to_thread(judger.judge, case.request)
        record = store_as(JudgeRecord)
        record.done, record.why = response.done, response.why
        return state

    return solve


@scorer(metrics={name: [confusion_count()] for name in ("TP", "FP", "FN", "TN")})
def judge_scorer() -> Scorer:
    """四格值为 0/1；汇总各格次数，标签独立于模型输出。"""

    async def score(state: TaskState, target: Target) -> Score:
        case = JudgeCase.model_validate(state.metadata["case"])
        record = store_as(JudgeRecord)
        assert record.done is not None, "solver 未写裁决"
        return Score(value=confusion(record.done, case.achieved), explanation=record.why)

    return score


@task
def judge(dataset: str = str(DATASET), judge_model: str | None = None) -> Task:
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
