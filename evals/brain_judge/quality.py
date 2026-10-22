"""judge 依据质量单列评分；完整决策准确率仍来自独立标签。"""

from inspect_ai.scorer import NOANSWER, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.common.advisory_quality import assess
from evals.common.quality_metrics import quality_count, quality_mean
from evals.dataset.brain_calls.dataset_contract import ReferenceCase
from pokemon_agent.schemas.harness.domain.judgement import Judgement

from .solver import JudgeRecord


@scorer(metrics=[quality_mean(), quality_count()])
def judge_quality(grader_model: str = "none") -> Scorer:
    """缺少独立依据参考时不计质量分，不用原始模型响应生成真值。"""

    async def score(state: TaskState, target: Target) -> Score:
        reference = state.metadata["case"].get("reference")
        record = store_as(JudgeRecord)
        if reference is None:
            return Score(value=NOANSWER, explanation="没有独立的判定依据参考")
        assert record.decision is not None
        return await assess(
            grader_model,
            ReferenceCase.model_validate(reference),
            Judgement(decision=record.decision, why=record.why),
            record.calls,
        )

    return score
