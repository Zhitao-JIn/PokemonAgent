"""完整目标运行的 Inspect 评分。"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    Score,
    Scorer,
    Target,
    scorer,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.agent_short_goal_run.dataset import load as load_samples
from evals.agent_short_goal_run.scorer import RunStream, mechanical_scorer, red_line_scorer
from evals.agent_short_goal_run.scorer.judged import judged_accuracy, judged_count
from evals.agent_short_goal_run.solver.record import AgentRunRecord


@scorer(metrics=[judged_accuracy(), judged_count()])
def e2e_scorer(*, stall_limits: tuple[int, int], trace_backend: str = "local") -> Scorer:
    """e2e 的判定 scorer：统一 Scorer（机械 + 红线）→ inspect `Score`。

    真值口径不变：机械判定第一真源，红线命中即判负；value 用 inspect 的
    CORRECT / INCORRECT / NOANSWER 字面量（unjudgeable = NOANSWER）。证据 uuid 与
    run_id 进 metadata——View 钻取 ↔ Langfuse 定位的接线点。
    `stall_limits` 由 task 装配期从 `pokemon_agent.config` 快照进闭包（不读 live config）。
    `trace_backend` 与 run-one 的写账后端同源（langfuse 时 scorer 直问服务）。
    """

    async def score(state: TaskState, target: Target) -> Score:
        del target  # 机械真值在游戏内存里，不在数据集 target 上
        sample_id = str(state.metadata["sample_id"])
        epoch = int(state.epoch)
        sample = next(
            s
            for s in load_samples(str(state.metadata["dataset_version"]))
            if s.sample_id == sample_id
        )
        record = store_as(AgentRunRecord)
        run_id = record.run_id
        if record.invalid:
            return Score(
                value=NOANSWER,
                explanation=f"run-one 记为无效：{record.invalid}",
                metadata={"run_id": run_id, "sample_id": sample_id, "epoch": epoch},
            )
        stream = RunStream.load(
            Path(record.work_dir) / "trace",
            run_id,
            branch=record.branch or None,
            backend=trace_backend,
        )
        mech = mechanical_scorer()(stream, sample)
        line = red_line_scorer(*stall_limits)(stream, sample)
        if line.outcome == "fail":
            value, explanation = INCORRECT, f"红线：{line.reason}"
        elif mech.outcome == "pass":
            value, explanation = CORRECT, mech.reason
        elif mech.outcome == "fail":
            value, explanation = INCORRECT, mech.reason
        else:
            value, explanation = NOANSWER, mech.reason or "不可机械判定"
        return Score(
            value=value,
            explanation=explanation,
            metadata={
                "run_id": run_id,
                "sample_id": sample_id,
                "epoch": epoch,
                "mech_outcome": mech.outcome,
                "red_line_outcome": line.outcome,
                "evidence": mech.evidence,
            },
        )

    return score
