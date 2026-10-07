"""pc_items 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def pc_withdraw_item(item: str, quantity: int, client_id: str | None = None) -> dict[str, Any]:
        """从 PC 取道具到背包"""
        return execute("pc_withdraw_item", client_id, {"item": item, "quantity": quantity})

    @mcp.tool()
    def pc_deposit_item(item: str, quantity: int, client_id: str | None = None) -> dict[str, Any]:
        """把背包里的道具存进 PC"""
        return execute("pc_deposit_item", client_id, {"item": item, "quantity": quantity})

    @mcp.tool()
    def pc_toss_item(item: str, quantity: int, client_id: str | None = None) -> dict[str, Any]:
        """丢掉 PC 里的道具；重要道具不能丢"""
        return execute("pc_toss_item", client_id, {"item": item, "quantity": quantity})
