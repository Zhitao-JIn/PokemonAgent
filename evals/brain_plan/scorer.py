"""plan 的约束评分与独立语义评分；不混成单个真值分数。"""

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.agent_short_goal_run.scorer.judged import judged_accuracy, judged_count
from evals.common.quality_metrics import quality_count, quality_mean
from evals.common.source_quality import assess
from evals.runconfig import ResultGraderConfig

from .compare import contract_checks
from .dataset import Case
from .solver import Record


@scorer(metrics=[judged_accuracy(), judged_count()])
def contract_scorer() -> Scorer:
    """只计可机械核对的当前请求约束，不冒称规划质量。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None, "solver must record an answer"
        checks = contract_checks(case.request, record.answer)
        return Score(value="C" if all(checks.values()) else "I", metadata={"checks": checks})

    return score


@scorer(metrics=[quality_mean(), quality_count()])
def quality_scorer(grader: ResultGraderConfig | None) -> Scorer:
    """逐条量表有证据才能判；评分缺失或无法确定不计入语义分母。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None, "solver must record an answer"
        return await assess(grader, case.reference, record.answer, record.calls)

    return score
