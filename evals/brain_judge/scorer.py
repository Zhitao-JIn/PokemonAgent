"""目标判定的四格评分。"""

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.brain_judge.metrics import judge_summary
from evals.brain_judge.solver import JudgeRecord
from evals.dataset.brain_judge import JudgeCase


def confusion(predicted: bool, achieved: bool) -> dict[str, int]:
    """一条样本只落入一个格；标签真值永不从模型文字反推。"""
    cell = ("TP" if achieved else "FP") if predicted else ("FN" if achieved else "TN")
    return {name: int(name == cell) for name in ("TP", "FP", "FN", "TN")}


@scorer(metrics=[judge_summary()])
def judge_scorer() -> Scorer:
    """汇总四格、派生率与分组指标；标签独立于模型输出。"""

    async def score(state: TaskState, target: Target) -> Score:
        case = JudgeCase.model_validate(state.metadata["case"])
        record = store_as(JudgeRecord)
        assert record.done is not None, "solver 未写裁决"
        raw_case = state.metadata["case"]
        origin = raw_case.get("origin", {}) if isinstance(raw_case, dict) else {}
        metadata = {
            "goal_family": raw_case.get("goal_family", "other"),
            "layer": raw_case.get("layer"),
            "negative_mode": raw_case.get("negative_mode"),
            "task_id": origin.get("task_id"),
            "episode_id": origin.get("episode_id"),
        }
        return Score(
            value=confusion(record.done, case.achieved),
            explanation=record.why,
            metadata=metadata,
        )

    return score
