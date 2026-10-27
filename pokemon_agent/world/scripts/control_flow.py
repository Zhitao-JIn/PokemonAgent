"""统一脚本结果与具名停止信号，预期失败由执行器转换为报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_types import ScriptReason


class Halt(Exception):
    """脚本内部控制流信号：被钩子 / 预算触发，由 `execute` 接住转成 `ScriptResult`。"""

    def __init__(self, code: str, *, ok: bool = False, extra: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code, self.ok, self.extra = code, ok, extra or {}


@dataclass
class ScriptResult:
    """一次脚本调用的终态报告（统一带 `events[]` 与现状快照）。

    `dialog` 是本次调用累计的对话**行**（不是帧、不是段）：脚本每按一键都会把
    屏幕上新出现的对话行收进 `DialogCache`，`finish` 把它摊平成一行一个元素。
    一口气按完的过场（领包裹、长对话）只在这里留下文字——`events[]` 记的是
    打在物体上的结果，不是屏幕上的话。
    """

    ok: bool
    code: str
    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    calls: list[Any] = field(default_factory=list)
    dialog: list[str] = field(default_factory=list)


class Abort(Exception):  # noqa: N818 —— 脚本内部的控制流信号，不出本包
    """未出现业务期望：执行器报告中止，并执行脚本明确声明的失败恢复。"""

    def __init__(self, code: ScriptReason, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason
