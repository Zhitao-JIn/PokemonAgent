"""scripts 测评：14 条 world 脚本在钉死存档上的真机验收（PLAN_mcp_servers 附录 A 的右列）。

入口 `inspect eval evals/tasks/world_actions/task.py`；用例在 `cases.py`，契约在 `schemas.py`。
"""

from __future__ import annotations

from .cases import CASES, CASES_BY_ID
from .schemas import (
    PROBE_KEYS,
    ScriptCase,
    ScriptEvent,
    ScriptExpect,
    ScriptReport,
    ScriptRun,
    ScriptRunRecord,
    ScriptVerdict,
)
from .scorer import judge_case, probe, script_scorer
from .solver import run_case, script_solver

__all__ = [
    "CASES",
    "CASES_BY_ID",
    "PROBE_KEYS",
    "ScriptCase",
    "ScriptEvent",
    "ScriptExpect",
    "ScriptReport",
    "ScriptRun",
    "ScriptRunRecord",
    "ScriptVerdict",
    "judge_case",
    "probe",
    "run_case",
    "script_scorer",
    "script_solver",
]
