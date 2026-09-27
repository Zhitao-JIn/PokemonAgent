"""机械判定器（code-based grader）：`judge(stream, sample)` 是唯一入口。只做 re-export。"""

from __future__ import annotations

from . import rules  # noqa: E402,I001  —— 导入即登记，须在注册表之后
from .registry import RULES, Check, judge, rule
from .stream import Frame, RunStream

__all__ = ["RULES", "Check", "Frame", "RunStream", "judge", "rule", "rules"]
