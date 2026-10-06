"""命令行分派：`python -m evals <测评> <命令> …`，把余下参数原样交给该测评自己的 `cli.main`。"""

from __future__ import annotations

import importlib
import sys

SUITES: dict[str, str] = {
    "e2e": "evals.e2e.cli",
    "macros": "evals.tasks.macros.cli",
    "screen": "evals.tasks.screen_reading.cli",
    "views": "evals.tasks.takeover_views.cli",
}
"""测评名 → 它的命令行模块。"""


def main(argv: list[str] | None = None) -> int:
    """取第一个参数定测评，其余交给它。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in SUITES:
        print(f"用法：python -m evals <{'|'.join(SUITES)}> <命令> …", file=sys.stderr)
        return 2
    module = importlib.import_module(SUITES[args[0]])
    return int(module.main(args[1:]))


__all__ = ["SUITES", "main"]
