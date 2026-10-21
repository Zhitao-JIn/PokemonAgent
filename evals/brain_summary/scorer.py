"""机械契约与独立 AI 五维评价分别计分；不评 harness 后加的来源章。"""

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from .contract import Layer, SummaryAnswer
from .dataset import Case
from .grading import assess
from .metrics import summary_contract, summary_quality
from .solver import Record


def contract_checks(layer: Layer, answer: SummaryAnswer) -> dict[str, bool]:
    """解析类型/数值由生产 Pydantic 保证；正文非空约束服从各层实际 prompt。"""
    return {
        "summary_nonempty": bool(answer.summary.strip()),
        "reason_nonempty": bool(answer.reason.strip()),
        "quality_rationale_nonempty": bool(answer.quality_rationale.strip()),
        "markdown_nonempty_if_required": layer == "task" or bool(answer.markdown.strip()),
    }


@scorer(metrics=[summary_contract()])
def contract_scorer() -> Scorer:
    """只给已解析候选的机械正文约束；解析耗尽仍由 Inspect 报 sample error。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None
        checks = contract_checks(case.layer, record.answer)
        return Score(
            value="C" if all(checks.values()) else "I",
            metadata={"layer": case.layer, "checks": checks},
        )

    return score


@scorer(metrics=[summary_quality()])
def quality_scorer(model: str) -> Scorer:
    """只让评分员看本次真实发送账和候选正文，不传完整请求或来源章。"""

    async def score(state: TaskState, target: Target) -> Score:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        assert record.answer is not None
        return await assess(model, case.layer, case.reference, record.answer, record.calls)

    return score
