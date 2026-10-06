"""`FromHarnessToGameToolExecuteResp`：`GameTool` → harness 的执行结果。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromHarnessToGameToolExecuteResp(BaseModel):
    """一次 `execute` 的结果：脚本动作带终态报告，按键动作带本键的裸事件。

    `report` 是脚本层 `ScriptResult` 的 JSON 形状（`{ok, code, data, events, calls}`）
    ——MCP 面上脚本 tool 本就返回这个形状，进程内路径同形折过去，两条通道一致。
    """

    report: dict[str, Any] | None = Field(
        default=None,
        description="脚本的终态报告（ok/code/data/events/calls）；按键为 None",
    )
    event: dict[str, Any] | None = Field(
        default=None,
        description="本键的裸对象事件（P6 起由 world 侧判定，step 路径）；脚本动作为 None"
        "——脚本的事件在 report.events[] 里批量带",
    )
