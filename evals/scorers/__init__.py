"""机械判定器（code-based grader）。

`judge(stream, sample)` 是注册表唯一入口；协议收敛后（`scoring/`）降为统一 Scorer 的
内部实现——判定消费方走 `scoring.mechanical_scorer` / `scoring.red_line_scorer`，
不许直调本包。只做 re-export。
"""

from __future__ import annotations

from . import rules  # noqa: E402,I001  —— 导入即登记，须在注册表之后
from .registry import RULES, Check, judge, rule
from .stream import Frame, RunStream

__all__ = ["RULES", "Check", "Frame", "RunStream", "judge", "rule", "rules"]
