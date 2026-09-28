"""一条样本的全部判定：读它的落盘账本，出 `SampleResult`。纯函数，可反复重算。

批跑在 `runs/<sample_id>/run.json` 记下跑的结果（`run_id`、`invalid` 原因）；这里只读盘。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.e2e.checks import RunStream, judge
from evals.e2e.process import judge_cells, sense_agreement, task_terminations
from evals.e2e.rubric import REDUNDANT, human_scores, score_redundant_path
from evals.e2e.schemas import EvalSample, SampleResult

from .efficiency import efficiency
from .redlines import red_lines

RUN_RECORD = "run.json"
"""批跑写在每条样本工作目录里的小结：`{"run_id", "invalid", "error"}`。"""


def evaluate(sample: EvalSample, run_dir: Path, report_dir: Path) -> SampleResult:
    """判一条样本。工作目录缺失或批跑标了无效时，返回只带 `invalid` 的结果。"""
    base = SampleResult(sample_id=sample.sample_id, category=sample.category, split=sample.split)
    record_path = run_dir / RUN_RECORD
    if not record_path.is_file():
        return base.model_copy(update={"invalid": "没有批跑记录（没跑或中途被杀）"})
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("invalid"):
        return base.model_copy(
            update={"invalid": record["invalid"], "run_id": record.get("run_id", "")}
        )

    # 步骤 1：读账、跑机械判据与红线。
    stream = RunStream.load(run_dir / "trace", record["run_id"])
    verdict = judge(stream, sample)
    hits = red_lines(stream, verdict)
    end = stream.run_end()

    # 步骤 2：过程集、rubric、效率。
    rubric = [score_redundant_path(stream, sample)] if REDUNDANT in sample.rubric else []
    rubric += human_scores(report_dir, sample)
    return base.model_copy(
        update={
            "run_id": record["run_id"],
            "branch": stream.branch,
            "termination": end.termination if end is not None else "",
            "red_lines": hits,
            "verdict": verdict,
            "final": "fail" if hits else verdict.outcome,
            "judge": judge_cells(stream, sample.sample_id, verdict),
            "task_terminations": task_terminations(stream, sample.sample_id),
            "rubric": rubric,
            "efficiency": efficiency(stream),
            "sense": sense_agreement(stream),
        }
    )


__all__ = ["RUN_RECORD", "evaluate"]
