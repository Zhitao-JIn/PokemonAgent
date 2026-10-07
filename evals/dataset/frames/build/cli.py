"""帧数据集的命令行：`python -m evals frames build`，从仓库根运行。

build --capture 目录 [--version v2]     从新采集记录重造数据集（产物冻结进仓库）

测评经 decode、episode_vision_read 两个 inspect task 执行。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .build import build_v2


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行，返回退出码。"""
    parser = argparse.ArgumentParser(prog="python -m evals frames")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--version", default="v2")
    p.add_argument("--capture", required=True, help="v2 起：人工采集目录（含 manifest.jsonl）")
    args = parser.parse_args(argv)

    print(f"数据集：{build_v2(Path(args.capture), args.version)}")
    return 0


__all__ = ["main"]
