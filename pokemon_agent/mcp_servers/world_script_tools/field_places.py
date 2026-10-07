"""field_places 的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有签名；租约与执行由 server 注入。"""

    @mcp.tool()
    def buy_item(item: str, count: int, client_id: str | None = None) -> dict[str, Any]:
        """脚本 buy_item：按 tables 在售表买道具；终态对账（扣款/入库）→ verify_failed 兜底。"""
        return execute("buy_item", client_id, {"item": item, "count": count})

    @mcp.tool()
    def sell_item(item: str, count: int, client_id: str | None = None) -> dict[str, Any]:
        """脚本 sell_item：把背包道具卖给店（卖价=买价一半）；终态对账 → verify_failed 兜底。"""
        return execute("sell_item", client_id, {"item": item, "count": count})

    @mcp.tool()
    def exit_map(target_warp: int = -1, client_id: str | None = None) -> dict[str, Any]:
        """脚本 exit_map：查 tables/warps[map_id] 的出口换图；踩到出口→ok（新图），"""
        return execute("exit_map", client_id, {"target_warp": target_warp})

    @mcp.tool()
    def heal_at_center(max_steps: int = 60, client_id: str | None = None) -> dict[str, Any]:
        """脚本 heal_at_center：宝可梦中心回满血（走到护士前→面朝护士→对话→机械确认"""
        return execute("heal_at_center", client_id, {"max_steps": max_steps})
