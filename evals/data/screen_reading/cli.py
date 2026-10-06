"""读屏数据集的命令行：`python -m evals screen build`，从仓库根运行。

build [--version v1] [--capture 目录]     重造数据集（要 ROM；产物冻结进仓库）

测评经 decode、vision_perceive、screen_interpret 三个 inspect task 执行。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .build import build, build_v2


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行，返回退出码。"""
    parser = argparse.ArgumentParser(prog="python -m evals screen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--version", default="v1")
    p.add_argument("--capture", default="", help="v2 起：人工采集目录（含 manifest.jsonl）")
    args = parser.parse_args(argv)

    if args.capture:
        print(f"数据集：{build_v2(Path(args.capture), args.version)}")
    else:
        print(f"数据集：{build(args.version)}")
    return 0


__all__ = ["main"]
