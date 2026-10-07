"""bag 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def bag_use(item: str, pokemon: str = "", client_id: str | None = None) -> dict[str, Any]:
        """用道具：药、进化石、营养剂、RARE CANDY 对一只队员用；驱虫喷雾直接用"""
        return execute("bag_use", client_id, {"item": item, "pokemon": pokemon})

    @mcp.tool()
    def bag_toss(item: str, quantity: int, client_id: str | None = None) -> dict[str, Any]:
        """丢道具；重要道具不能丢"""
        return execute("bag_toss", client_id, {"item": item, "quantity": quantity})

    @mcp.tool()
    def bag_close(client_id: str | None = None) -> dict[str, Any]:
        """关上背包"""
        return execute("bag_close", client_id, {})
