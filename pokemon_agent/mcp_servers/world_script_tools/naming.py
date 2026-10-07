"""naming 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def naming_enter_name(name: str, client_id: str | None = None) -> dict[str, Any]:
        """输入名字并提交（会先删掉已经输入的字）"""
        return execute("naming_enter_name", client_id, {"name": name})
