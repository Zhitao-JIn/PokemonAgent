"""批跑：只落盘、不判定。只做 re-export（`run_one` 懒加载：它拖着模拟器与模型客户端）。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .batch import RESULTS_ROOT, run_batch

if TYPE_CHECKING:
    from .one import run_one

__all__ = ["RESULTS_ROOT", "run_batch", "run_one"]


def __getattr__(name: str) -> Any:  # noqa: ANN401
    """`run_one` 按需导入。"""
    if name != "run_one":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = importlib.import_module(".one", __name__).run_one
    globals()[name] = value
    return value
