"""读屏测评的命令行：`python -m evals screen <命令>`，从仓库根运行。

build                                          重造数据集（要 ROM；产物冻结进仓库）
run [--model M] [--limit N] [--samples a,b] [--workers 8]
                                               跑一批并出报告与核对页；不给 --model 只算解码直出
report <报告目录>                               按 results.jsonl 重算报告与核对页（review.html）
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .build import REPO_ROOT, build, build_v2
from .report import build_report
from .review_page import build_review
from .run import run_suite


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行，返回退出码。"""
    parser = argparse.ArgumentParser(prog="python -m evals screen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--version", default="v1")
    p.add_argument("--capture", default="", help="v2 起：人工采集目录（含 manifest.jsonl）")
    p = sub.add_parser("run")
    p.add_argument("--version", default="v1")
    p.add_argument("--model", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--samples", default="")
    p.add_argument("--workers", type=int, default=8)
    p = sub.add_parser("report")
    p.add_argument("report_dir")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        if args.capture:
            print(f"数据集：{build_v2(Path(args.capture), args.version)}")
        else:
            print(f"数据集：{build(args.version)}")
    elif args.cmd == "run":
        _load_env(REPO_ROOT / ".env")
        report_dir = run_suite(
            args.version,
            model=args.model,
            limit=args.limit,
            workers=args.workers,
            sample_ids=[s for s in args.samples.split(",") if s] or None,
        )
        print(f"报告：{build_report(report_dir)}")
        print(f"核对页：{build_review(report_dir)}")
    else:
        print(f"报告：{build_report(Path(args.report_dir))}")
        print(f"核对页：{build_review(Path(args.report_dir))}")
    return 0


def _load_env(path: Path) -> None:
    """把 `.env` 的 KEY=VALUE 注入环境；外部已有的同名变量优先。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


__all__ = ["main"]
