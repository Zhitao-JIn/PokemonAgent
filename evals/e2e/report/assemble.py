"""出一份报告：读口径头与每条样本的账 → `results.jsonl` / `report.md` / `rubric_forms.md`，
追加 `bad_cases.jsonl`。

全部由盘上产物算出，删了能重算（intent §六-4）；人工打分写在 `rubric_scores.jsonl`，重算时读回。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.core.evallog import HEADER, RESULTS
from evals.data import load_rubric, load_samples
from evals.e2e.cases import append_new, collect
from evals.e2e.rubric import form_section
from evals.schema import ReportHeader, SampleResult
from evals.scorers import RunStream

from .evaluate import RUN_RECORD, evaluate, stall_limits_of
from .markdown import render

REPORT = "report.md"
FORMS = "rubric_forms.md"
BAD_CASES = "bad_cases.jsonl"


def build_report(report_dir: Path) -> list[SampleResult]:
    """判全部样本并落盘，返回结果。前置条件：`report_dir/header.json` 存在（批跑开始时写）。"""
    header = ReportHeader.model_validate_json((report_dir / HEADER).read_text(encoding="utf-8"))
    rubric = load_rubric(header.dataset_version)
    samples = [s for s in load_samples(header.dataset_version) if s.sample_id in header.sample_ids]

    # 步骤 1：逐条判（红线阈值来自口径头快照，不读 live config）。
    limits = stall_limits_of(header)
    results = [
        evaluate(s, report_dir / "runs" / s.sample_id, report_dir, stall_limits=limits)
        for s in samples
    ]
    (report_dir / RESULTS).write_text(
        "".join(json.dumps(r.model_dump(), ensure_ascii=False) + "\n" for r in results),
        encoding="utf-8",
    )

    # 步骤 2：bad case 与人工打分表。
    cases = collect(header.report_id, results)
    append_new(report_dir / BAD_CASES, cases)
    forms = [
        f"# 人工打分表 {header.report_id}",
        "",
        f"分数写进 `{report_dir.name}/rubric_scores.jsonl`。",
        "",
    ]
    for sample, result in zip(samples, results, strict=True):
        if result.invalid:
            continue
        record = json.loads(
            (report_dir / "runs" / sample.sample_id / RUN_RECORD).read_text("utf-8")
        )
        stream = RunStream.load(report_dir / "runs" / sample.sample_id / "trace", record["run_id"])
        forms.append(form_section(stream, sample, rubric))
    (report_dir / FORMS).write_text("\n".join(forms), encoding="utf-8")

    # 步骤 3：给人读的报告。
    (report_dir / REPORT).write_text(render(header, results, len(cases)), encoding="utf-8")
    return results


__all__ = ["BAD_CASES", "FORMS", "HEADER", "REPORT", "RESULTS", "build_report"]
