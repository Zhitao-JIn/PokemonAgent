"""接管视图测评的命令行：`python -m evals views <命令>`，从仓库根运行。

run [--cases a,b]      跑一批用例，出 `results.jsonl` 与 `report.md`
"""

from __future__ import annotations

import argparse

from .run import REPORT, run_suite


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行；有用例没过时返回 1。"""
    parser = argparse.ArgumentParser(prog="python -m evals views")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--cases", default="")
    args = parser.parse_args(argv)
    report_dir = run_suite([c for c in args.cases.split(",") if c] or None)
    report = (report_dir / REPORT).read_text(encoding="utf-8")
    print(report)
    print(f"报告：{report_dir / REPORT}")
    return 0 if "❌" not in report else 1


__all__ = ["main"]
