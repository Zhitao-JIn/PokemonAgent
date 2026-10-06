"""脚本终态报告的一行描述：`act` 写 `last_result`、ActMemory 写 `result`、停摆键共用这一条规则。

报告是脚本层 `ScriptResult` 的 JSON 形状（`{ok, code, data, events, calls}`）；`data` 里
有 `summary`（执行到位时的状态变化）或 `reason`（没到位时的原因）就接在结局码后面。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.brain import Action


def result_line(report: dict[str, Any]) -> str:
    """`ok：钱 3000→2000` / `not_enough_money：钱不够`；没有摘要与原因时只有结局码。"""
    code = str(report.get("code", ""))
    data = report.get("data")
    detail = str(data.get("summary") or data.get("reason") or "") if isinstance(data, dict) else ""
    return f"{code}：{detail}" if detail else code


def describe_call(action: Action, report: dict[str, Any]) -> str:
    """一次脚本调用连同结果：`script:buy_item(item=POKé BALL, count=5) → ok：钱 3000→2000`。"""
    return f"{action.describe()} → {result_line(report)}"


__all__ = ["describe_call", "result_line"]
