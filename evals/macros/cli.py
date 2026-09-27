"""宏测评的命令行：`python -m evals macros <命令>`，从仓库根运行。

run [--cases a,b]      跑一批用例，出 `results.jsonl` 与 `report.md`
list                   列出全部用例
"""

from __future__ import annotations

import argparse

from .cases import CASES
from .run import REPORT, run_suite


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行；有用例没过时返回 1。"""
    parser = argparse.ArgumentParser(prog="python -m evals macros")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--cases", default="")
    sub.add_parser("list")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for case in CASES:
            print(f"{case.case_id}\t{case.state}\t{case.macro}{case.args}\t{case.status.value}")
        return 0
    report_dir = run_suite([c for c in args.cases.split(",") if c] or None)
    report = (report_dir / REPORT).read_text(encoding="utf-8")
    print(report)
    print(f"报告：{report_dir / REPORT}")
    return 0 if "❌" not in report else 1


__all__ = ["main"]
