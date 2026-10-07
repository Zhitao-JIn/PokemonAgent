"""目标判定的四格评分。"""

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.dataset.brain_goal_judge import JudgeCase
from evals.scorers.judge_metrics import confusion_count
from evals.solvers.brain_goal_judge import JudgeRecord


def confusion(predicted: bool, achieved: bool) -> dict[str, int]:
    """一条样本只落入一个格；标签真值永不从模型文字反推。"""
    cell = ("TP" if achieved else "FP") if predicted else ("FN" if achieved else "TN")
    return {name: int(name == cell) for name in ("TP", "FP", "FN", "TN")}


@scorer(metrics={name: [confusion_count()] for name in ("TP", "FP", "FN", "TN")})
def judge_scorer() -> Scorer:
    """四格值为 0/1；汇总各格次数，标签独立于模型输出。"""

    async def score(state: TaskState, target: Target) -> Score:
        case = JudgeCase.model_validate(state.metadata["case"])
        record = store_as(JudgeRecord)
        assert record.done is not None, "solver 未写裁决"
        return Score(value=confusion(record.done, case.achieved), explanation=record.why)

    return score
