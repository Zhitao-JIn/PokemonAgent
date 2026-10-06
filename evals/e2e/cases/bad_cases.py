"""bad case 登记（spec §十、intent §七）：红线命中、机械判负、judge 假阳 / 假阴都登记。

只存指针（报告、样本、run、证据 uuid），`triage` 起始为 pending；文件只追加、不删除，
同一份报告重算时不重复登记。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.schema import BadCase, SampleResult


def collect(report_id: str, results: list[SampleResult]) -> list[BadCase]:
    """从这份报告的结果里挑出 bad case。无效样本不登记。"""
    cases: list[BadCase] = []
    for r in results:
        if r.invalid:
            continue
        common = {"report_id": report_id, "sample_id": r.sample_id, "run_id": r.run_id}
        for hit in r.red_lines:
            cases.append(
                BadCase(
                    **common,
                    trigger="red_line",
                    evidence=hit.evidence,
                    reason=f"{hit.line_id}：{hit.reason}",
                )
            )
        if r.verdict is not None and r.verdict.outcome == "fail":
            cases.append(
                BadCase(
                    **common,
                    trigger="mech_fail",
                    evidence=r.verdict.evidence,
                    reason=r.verdict.reason,
                )
            )
        for cell in r.judge:
            if cell.cell in ("FP", "FN"):
                trigger = "judge_fp" if cell.cell == "FP" else "judge_fn"
                cases.append(
                    BadCase(**common, trigger=trigger, reason=f"{cell.layer} 层 judge {cell.cell}")
                )
    return cases


def append_new(path: Path, cases: list[BadCase]) -> int:
    """把没登记过的追加进去（按 报告 + 样本 + 触发类型 + 理由 去重），返回新增条数。"""
    seen: set[tuple[str, str, str, str]] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = BadCase.model_validate_json(line)
                seen.add((row.report_id, row.sample_id, row.trigger, row.reason))
    fresh = [c for c in cases if (c.report_id, c.sample_id, c.trigger, c.reason) not in seen]
    with path.open("a", encoding="utf-8") as out:
        for case in fresh:
            out.write(json.dumps(case.model_dump(), ensure_ascii=False) + "\n")
    return len(fresh)


__all__ = ["append_new", "collect"]
