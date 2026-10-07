"""shop 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def shop_quit(client_id: str | None = None) -> dict[str, Any]:
        """结束买卖，离开这个菜单"""
        return execute("shop_quit", client_id, {})
