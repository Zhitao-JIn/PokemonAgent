"""两份报告对比（spec §十）：口径不同就拒绝；口径相同按样本列出结论翻转。

显著性检验等 k>1 与 intent V6 定了再加。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.schema import COMPARABLE_FIELDS, ReportHeader, SampleResult

HEADER = "header.json"
"""报告目录里的口径头文件名（V9 的 manifest 载体；assemble 与 diff 共用，定义唯一起源在此）。"""

RESULTS = "results.jsonl"
"""报告目录里的逐样本判定结果文件名。"""


def diff(a: Path, b: Path) -> str:
    """对比两个报告目录，返回一段 markdown。"""
    ha = ReportHeader.model_validate_json((a / HEADER).read_text(encoding="utf-8"))
    hb = ReportHeader.model_validate_json((b / HEADER).read_text(encoding="utf-8"))
    mismatched = [f for f in COMPARABLE_FIELDS if getattr(ha, f) != getattr(hb, f)]
    if mismatched:
        rows = "\n".join(f"| {f} | {getattr(ha, f)} | {getattr(hb, f)} |" for f in mismatched)
        head = f"| 口径 | {ha.report_id} | {hb.report_id} |\n|---|---|---|"
        return f"# 拒绝对比：口径不同\n\n{head}\n{rows}\n"
    ra, rb = _results(a), _results(b)
    lines = [
        f"# {ha.report_id} → {hb.report_id}",
        "",
        f"代码：{ha.git_commit} → {hb.git_commit}",
        "",
        "| 样本 | 之前 | 之后 |",
        "|---|---|---|",
    ]
    flips = 0
    for sid in sorted(set(ra) & set(rb)):
        before, after = ra[sid].final, rb[sid].final
        if before != after:
            flips += 1
            lines.append(f"| {sid} | {before} | {after} |")
    if not flips:
        lines.append("| （无翻转） | | |")
    return "\n".join(lines) + "\n"


def _results(report_dir: Path) -> dict[str, SampleResult]:
    """读 `results.jsonl`，按样本索引；无效样本不参与对比。"""
    out: dict[str, SampleResult] = {}
    for line in (report_dir / RESULTS).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = SampleResult.model_validate(json.loads(line))
            if not r.invalid:
                out[r.sample_id] = r
    return out


__all__ = ["diff"]
