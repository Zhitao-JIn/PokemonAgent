"""e2e 的模型结果评分：只读目标、判据与最终机械观测，不给过程评分。"""

import json
from pathlib import Path

from inspect_ai.model import get_model
from inspect_ai.scorer import NOANSWER, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as
from pydantic import BaseModel, ValidationError

from evals.dataset.agent_goal_run import load as load_samples
from evals.scorers import RunStream
from evals.scorers.judged import judged_accuracy, judged_count
from evals.solvers.agent_goal_run.record import AgentRunRecord


class ResultGrade(BaseModel):
    """评分模型的独立结果结论。"""

    achieved: bool
    reason: str


def final_evidence(record: AgentRunRecord, backend: str) -> str | None:
    """从最终帧拿机械观测；无完整记录或无 RAM 时不可判。"""
    if record.invalid:
        return None
    stream = RunStream.load(
        Path(record.work_dir) / "trace",
        record.run_id,
        branch=record.branch or None,
        backend=backend,
    )
    frames = stream.frames()
    if not frames or frames[-1].content.ram is None:
        return None
    frame = frames[-1].content
    return json.dumps(
        {
            "place": frame.place.model_dump() if frame.place else None,
            "ram": frame.ram.model_dump(mode="json"),
        },
        ensure_ascii=False,
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
        evidence = final_evidence(store_as(AgentRunRecord), backend)
        if evidence is None:
            return Score(value=NOANSWER, explanation="没有可用的最终机械观测")
        prompt = (
            f"只判结果是否达成，不评路径、效率或模型自述。\n目标：{sample.goal}\n"
            f"判据：{sample.success_criteria}\n最终机械观测：{evidence}\n"
            '只回 JSON：{"achieved": true或false, "reason": "观测证据"}'
        )
        output = await get_model(grader_model).generate(prompt)
        try:
            grade = ResultGrade.model_validate_json(
                output.completion.strip().removeprefix("```json").removesuffix("```").strip()
            )
        except ValidationError as exc:
            return Score(
                value=NOANSWER,
                explanation=f"评分解析失败：{exc}",
                metadata={"raw": output.completion},
            )
        return Score(
            value="C" if grade.achieved else "I",
            explanation=grade.reason,
            metadata={"model": grader_model, "raw": output.completion},
        )

    return score
