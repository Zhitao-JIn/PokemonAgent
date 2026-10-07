"""MCP 脚本注册的执行回调类型；结果是传输层 JSON 信封。"""

from collections.abc import Callable
from typing import Any

ScriptExecutor = Callable[[str, str | None, dict[str, str | int | float | None]], dict[str, Any]]
