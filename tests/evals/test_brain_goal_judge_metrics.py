"""brain_goal_judge 混淆矩阵与分组统计示例。"""

from math import isnan
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import SampleScore, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState

from evals.brain_goal_judge.metrics import JudgeObservation, judge_summary, summarize


@scorer(metrics=[judge_summary()])
def fake_summary_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(
            value={"TP": 1, "FP": 0, "FN": 0, "TN": 0},
            metadata=state.metadata,
        )

    return score


def test_judge_summary_reports_rates_denominators_and_unique_sources() -> None:
    observations = [
        JudgeObservation(True, True, "navigation", None, "t1", "e1"),
        JudgeObservation(True, False, "navigation", "near_miss", "t1", "e1"),
        JudgeObservation(False, True, "interaction", None, "t2", "e2"),
        JudgeObservation(False, False, "interaction", "required_state_missing", "t3", "e2"),
    ]

    result = summarize(observations)

    assert (result["overall_TP"], result["overall_FP"]) == (1, 1)
    assert (result["overall_FN"], result["overall_TN"]) == (1, 1)
    assert result["overall_fpr"] == 0.5
    assert result["overall_fpr_denominator"] == 2
    assert result["overall_recall"] == 0.5
    assert result["overall_precision"] == 0.5
    assert result["overall_accuracy"] == 0.5
    assert result["overall_unique_tasks"] == 3
    assert result["overall_unique_episodes"] == 2
    assert result["goal_family.navigation.TP"] == 1
    assert result["goal_family.navigation.FP"] == 1
    assert result["negative_mode.near_miss.FP"] == 1
    assert result["negative_mode.near_miss.TN"] == 0
    assert result["negative_mode.near_miss.fpr_denominator"] == 1


def test_judge_summary_uses_na_rates_for_zero_denominators() -> None:
    result = summarize([JudgeObservation(True, True, "navigation", None, "t1", "e1")])

    assert isnan(result["overall_fpr"])
    assert result["overall_fpr_denominator"] == 0
    assert result["overall_recall"] == 1.0


def test_inspect_metric_reads_case_groups_from_score_metadata() -> None:
    score = SampleScore(
        score=Score(
            value={"TP": 0, "FP": 1, "FN": 0, "TN": 0},
            metadata={
                "goal_family": "interaction",
                "negative_mode": "near_miss",
                "task_id": "task-1",
                "episode_id": "episode-1",
            },
        )
    )

    result = judge_summary()([score])

    assert result["overall_FP"] == 1
    assert result["goal_family.interaction.FP"] == 1
    assert result["negative_mode.near_miss.FP"] == 1


def test_inspect_task_emits_judge_summary_without_model_call(tmp_path: Path) -> None:
    task = Task(
        dataset=[
            Sample(
                id="case-1",
                input="frozen input",
                metadata={
                    "goal_family": "navigation",
                    "negative_mode": None,
                    "task_id": "task-1",
                    "episode_id": "episode-1",
                },
            )
        ],
        solver=[],
        scorer=fake_summary_scorer(),
        model="none",
    )

    log = eval(task, log_dir=str(tmp_path), display="none")[0]

    assert log.status == "success", log.error
    assert log.results is not None
    metrics = {metric.name: metric.value for metric in log.results.scores[0].metrics.values()}
    assert metrics["overall_TP"] == 1.0
    assert metrics["goal_family.navigation.TP"] == 1.0
    assert isnan(metrics["overall_fpr"])
    assert metrics["overall_fpr_denominator"] == 0.0
