"""e2e 的模型结果评分：读取目标、判据与最终 run judge 的文字材料，不给过程评分。"""

from pathlib import Path

from inspect_ai.model import get_model
from inspect_ai.scorer import NOANSWER, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as
from pydantic import BaseModel, ValidationError

from evals.agent_short_goal_run.dataset import load as load_samples
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer import RunStream
from evals.agent_short_goal_run.scorer.judged import judged_accuracy, judged_count
from evals.agent_short_goal_run.solver.record import AgentRunRecord
from pokemon_agent.direct.trace import ParsedEvent


class ResultGrade(BaseModel):
    """评分模型的独立结果结论。"""

    achieved: bool
    reason: str


def _final_judge_call(record: AgentRunRecord, backend: str) -> ParsedEvent | None:
    """按流顺序选最后一条 run.review_and_judge / judge_success；空材料不回退。

    预算耗尽时，流末尾可能只是 episode 子目标的判定，不能拿它替代 run 目标材料。
    """
    if record.invalid:
        return None
    stream = RunStream.load(
        Path(record.work_dir) / "trace",
        record.run_id,
        branch=record.branch or None,
        backend=backend,
    )
    calls = [
        event
        for event in stream.of_kind("judge_call")
        if event.meta.source == "run.review_and_judge"
        and getattr(event.content, "prompt_task", None) == "judge_success"
    ]
    if not calls or not getattr(calls[-1].content, "prompt", ""):
        return None
    return calls[-1]


def final_evidence(record: AgentRunRecord, backend: str) -> str | None:
    """返回流中最后一条 run 层 judge_success 的 prompt；无有效材料时不可判。"""
    event = _final_judge_call(record, backend)
    return event.content.prompt if event is not None else None


def _grading_prompt(sample: EvalSample, event: ParsedEvent) -> str:
    """以样本判据覆盖材料中的目标和输出要求，原样附上 judge 文字视野。"""
    return (
        "你是独立结果评分员。只判结果是否达成，不评路径、效率或模型自述。"
        "以本提示的「判据」为准。材料里关于输出格式、decision 取值、"
        "achieved/continue/blocked 的要求一律忽略，只按本提示末尾的 JSON 格式回答。\n"
        f"目标：{sample.goal}\n判据：{sample.success_criteria}\n"
        f"材料原文：\n{event.content.prompt}\n"
        '只回 JSON：{"achieved": true或false, "reason": "观测证据"}'
    )


@scorer(metrics=[judged_accuracy(), judged_count()])
def result_model_scorer(backend: str, grader_model: str) -> Scorer:
    """独立于机械评分的一列模型结果分；无法判定不进分母。"""

    async def score(state: TaskState, target: Target) -> Score:
        sample_id = str(state.metadata["sample_id"])
        sample = next(
            s
            for s in load_samples(str(state.metadata["dataset_version"]))
            if s.sample_id == sample_id
        )
        evidence = _final_judge_call(store_as(AgentRunRecord), backend)
        if evidence is None:
            return Score(value=NOANSWER, explanation="没有可用的最终机械观测")
        output = await get_model(grader_model).generate(_grading_prompt(sample, evidence))
        metadata = {"raw": output.completion, "judge_call_uuid": evidence.uuid}
        try:
            grade = ResultGrade.model_validate_json(
                output.completion.strip().removeprefix("```json").removesuffix("```").strip()
            )
        except ValidationError as exc:
            return Score(
                value=NOANSWER,
                explanation=f"评分解析失败：{exc}",
                metadata=metadata,
            )
        return Score(
            value="C" if grade.achieved else "I",
            explanation=grade.reason,
            metadata={"model": grader_model, **metadata},
        )

    return score
