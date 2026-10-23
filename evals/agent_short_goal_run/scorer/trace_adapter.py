"""Adapt pure trace measurements to independent Inspect scorers, without model grading."""

from pathlib import Path

from inspect_ai.scorer import NOANSWER, Score, Scorer, Target
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.agent_short_goal_run.dataset import EvalSample, load
from evals.agent_short_goal_run.solver.record import AgentRunRecord

from .measurement import Measurement, TraceMeasurement
from .scorer import mechanical_scorer, red_line_scorer
from .stream import RunStream


def _score_metadata(
    stream: RunStream, result: Measurement, successful: bool | None, check_id: str | None
) -> dict[str, object]:
    """Attach outcome and trace evidence independently of scorer execution order."""
    end = stream.run_end()
    return {
        "successful": successful,
        "termination": end.termination if end else "",
        "unit": result.unit,
        "evidence": result.evidence,
        "details": result.details,
        "check_id": check_id,
    }


def _successful(
    stream: RunStream, sample: EvalSample, stall_limits: tuple[int, int]
) -> bool | None:
    """Match e2e_scorer's red-line precedence without depending on another scorer's store."""
    mechanical = mechanical_scorer()(stream, sample)
    red_line = red_line_scorer(*stall_limits)(stream, sample)
    if red_line.outcome == "fail":
        return False
    if mechanical.outcome == "unjudgeable":
        return None
    return mechanical.outcome == "pass"


def trace_scorer(measure: TraceMeasurement, backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Build a scorer; caller supplies the same backend and stall limits as e2e_scorer.

    Incomplete runs are unavailable rather than deceptively cheap zeroes. Trace failures
    propagate; invalid worker records are excluded. This adapter never invokes a model.
    """

    async def score(state: TaskState, target: Target) -> Score:
        del target
        record = store_as(AgentRunRecord)
        metadata = {
            "sample_id": str(state.metadata["sample_id"]),
            "epoch": int(state.epoch),
            "run_id": record.run_id,
            "branch": record.branch,
            "trace_root": record.work_dir,
            "invalid": bool(record.invalid),
            "context_path": str(Path(record.work_dir).parent.parent / "baseline_context.json"),
        }
        if record.invalid:
            return Score(value=NOANSWER, explanation=record.invalid, metadata=metadata)
        stream = RunStream.load(
            Path(record.work_dir) / "trace",
            record.run_id,
            branch=record.branch or None,
            backend=backend,
        )
        sample = next(
            s
            for s in load(str(state.metadata["dataset_version"]))
            if s.sample_id == str(state.metadata["sample_id"])
        )
        successful = _successful(stream, sample, stall_limits)
        result = measure(stream, sample)
        metadata.update(_score_metadata(stream, result, successful, sample.check_id))
        if not stream.of_kind("run_start") or stream.run_end() is None:
            return Score(value=NOANSWER, explanation="Incomplete run boundaries", metadata=metadata)
        return Score(
            value=result.value if result.value is not None else NOANSWER,
            explanation=result.explanation,
            metadata=metadata,
        )

    return score
