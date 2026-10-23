"""动作合法性与 AI 合理性分开；不按参考动作集合命中计质量分。"""

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.agent_short_goal_run.scorer.judged import judged_accuracy, judged_count
from evals.common.quality_metrics import quality_count, quality_mean
from evals.common.source_quality import assess
from evals.runconfig import ResultGraderConfig
from pokemon_agent.brain.interface import Action
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq

from .dataset import Case
from .inspect_solver import Record


def contract_checks(
    request: FromHarnessToBrainToolChooseOnceReq, answer: Action
) -> dict[str, bool]:
    """按本次能力掩码和单步约定检查；具体策略合理性由独立 AI 判断。"""
    names = [answer.script.name] if answer.script else [segment.name for segment in answer.sequence]
    return {
        "enabled_action": all(request.space.enabled(name) for name in names),
        "single_step": answer.script is not None
        or sum(segment.times for segment in answer.sequence) == 1,
    }


@scorer(metrics=[judged_accuracy(), judged_count()])
def contract_scorer() -> Scorer:
    """结构分不替代策略质量分，不匹配建议也不视作结构错误。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None
        checks = contract_checks(case.request, record.answer)
        return Score(value="C" if all(checks.values()) else "I", metadata={"checks": checks})

    return score


@scorer(metrics=[quality_mean(), quality_count()])
def quality_scorer(grader: ResultGraderConfig | None) -> Scorer:
    """完整实际生产上下文交给 AI，允许多种动作与失败后合理纠偏。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None
        return await assess(grader, case.reference, record.answer, record.calls)

    return score
