"""一条样本的全部判定：主输入 = `run_result.json`（`RunResult`，V8/R2b），trace 只供判据取证据帧。

判定走统一 Scorer 协议（`evals/core/scorer.py`）：机械 / 红线 / judge 一致性三个 scorer
并列出 `Score`，本模块做**报告投影**（`verdict_of` / `hits_of`，R5 退役 `SampleResult`
时一并删）。效率层改从 `RunResult` 取数（R2b：eval 不再各读各的 trace）。
批跑在 `runs/<sample_id>/` 下写 `run.json`（小结）与 `run_result.json`（结构化返回值）；
这里只读盘。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.core import Score, mechanical_scorer, red_line_scorer
from evals.e2e.process import judge_agreement_scorer, sense_agreement, task_terminations
from evals.e2e.rubric import REDUNDANT, human_scores, score_redundant_path
from evals.schema import (
    CheckVerdict,
    Efficiency,
    EvalSample,
    JudgeCell,
    RedLineHit,
    ReportHeader,
    SampleResult,
    TokenUse,
)
from evals.scorers import RunStream
from pokemon_agent.schemas.harness.domain import RunResult

RUN_RECORD = "run.json"
"""批跑写在每条样本工作目录里的小结：`{"run_id", "invalid", "error"}`。"""

RUN_RESULT = "run_result.json"
"""批跑落盘的结构化返回值（`RunResult`，V8）——本模块的主输入。"""


def stall_limits_of(header: ReportHeader) -> tuple[int, int]:
    """口径头快照 → 红线刹车阈值（config 值是 repr 字符串，剥引号转 int）。"""

    def limit(key: str) -> int:
        return int(header.config[key].strip("'\""))

    return limit("EPISODE_STALL_LIMIT"), limit("RUN_STALL_LIMIT")


def verdict_of(mech: Score) -> CheckVerdict:
    """机械 `Score` → `SampleResult.verdict` 的报告投影。

    前置条件：`mech` 是机械 scorer 的产出（`scorer_id` 以 `mech:` 开头）；
    唯一产出方是本函数——报表层之外不许再造 `CheckVerdict`。
    """
    assert mech.scorer_id.startswith("mech:") and mech.outcome is not None, (
        "投影输入须是机械 scorer 的已判定 Score"
    )
    return CheckVerdict(outcome=mech.outcome, evidence=mech.evidence, reason=mech.reason)


def hits_of(line: Score) -> list[RedLineHit]:
    """红线 `Score` → `SampleResult.red_lines` 的报告投影（命中明细存在 `detail["hits"]`）。"""
    assert line.scorer_id == "red_lines", "投影输入必须是红线 scorer 的 Score"
    return [RedLineHit.model_validate(h) for h in line.detail.get("hits", [])]


def load_result(run_dir: Path) -> RunResult | None:
    """读批跑落盘的结构化返回值；R1 之前的旧产物没有这个文件 → `None`。"""
    path = run_dir / RUN_RESULT
    if not path.is_file():
        return None
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def _efficiency_of(result: RunResult) -> Efficiency:
    """`RunResult` → 报告效率层（字段映射；evals 不再自己读 trace 算开销）。"""
    return Efficiency(
        tokens_by_link={
            link: TokenUse(input=u.input, output=u.output, cached=u.cached, reasoning=u.reasoning)
            for link, u in result.usage.tokens_by_link.items()
        },
        calls_by_link=dict(result.usage.calls_by_link),
        call_failed=result.usage.call_failed,
        call_exhausted=result.usage.call_exhausted,
        presses=result.counts.presses,
        episodes=result.counts.episodes,
        tasks=result.counts.tasks,
        wall_seconds=round(result.ended_at - result.started_at, 3) if result.ended_at else 0.0,
    )


def evaluate(
    sample: EvalSample, run_dir: Path, report_dir: Path, *, stall_limits: tuple[int, int]
) -> SampleResult:
    """判一条样本。工作目录缺失、批跑标了无效、或没有结构化返回值时，返回只带 `invalid` 的结果。

    前置条件：`stall_limits` 来自口径头快照（`stall_limits_of(header)`）——
    红线阈值不读被测 live config（spec2 §二边界修正，330）。
    """
    base = SampleResult(sample_id=sample.sample_id, category=sample.category, split=sample.split)
    record_path = run_dir / RUN_RECORD
    if not record_path.is_file():
        return base.model_copy(update={"invalid": "没有批跑记录（没跑或中途被杀）"})
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("invalid"):
        return base.model_copy(
            update={"invalid": record["invalid"], "run_id": record.get("run_id", "")}
        )
    result = load_result(run_dir)
    if result is None:
        return base.model_copy(
            update={
                "invalid": "没有结构化返回值（run_result.json，R1 之前的旧产物）",
                "run_id": record.get("run_id", ""),
            }
        )

    # 步骤 1：统一 Scorer 判定——机械 / 红线 / judge 一致性并列出 Score（spec2 §六）。
    stream = RunStream.load(run_dir / "trace", result.run_id)
    mech = mechanical_scorer()(stream, sample)
    line = red_line_scorer(*stall_limits)(stream, sample)
    agreement = judge_agreement_scorer()(stream, sample)
    verdict = verdict_of(mech)
    hits = hits_of(line)
    assert mech.outcome is not None

    # 步骤 2：过程集、rubric、效率（效率层取数自 RunResult，R2b）。
    rubric = [score_redundant_path(stream, sample)] if REDUNDANT in sample.rubric else []
    rubric += human_scores(report_dir, sample)
    return base.model_copy(
        update={
            "run_id": result.run_id,
            "branch": result.branch,
            "termination": result.termination,
            "red_lines": hits,
            "verdict": verdict,
            "final": "fail" if hits else mech.outcome,
            "judge": [JudgeCell.model_validate(c) for c in agreement.detail["cells"]],
            "task_terminations": task_terminations(stream, sample.sample_id),
            "rubric": rubric,
            "efficiency": _efficiency_of(result),
            "sense": sense_agreement(stream),
        }
    )


__all__ = [
    "RUN_RECORD",
    "RUN_RESULT",
    "evaluate",
    "hits_of",
    "load_result",
    "stall_limits_of",
    "verdict_of",
]
