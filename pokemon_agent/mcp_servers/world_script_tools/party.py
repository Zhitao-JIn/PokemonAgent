"""party 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def party_switch(a: str, b: str, client_id: str | None = None) -> dict[str, Any]:
        """对调两只在队伍里的位置（排第一的先出场）"""
        return execute("party_switch", client_id, {"a": a, "b": b})

    @mcp.tool()
    def party_field_move(pokemon: str, move: str, client_id: str | None = None) -> dict[str, Any]:
        """使用队员的野外招式；支持 CUT/SURF 等，FLY 尚不支持。"""
        return execute("party_field_move", client_id, {"pokemon": pokemon, "move": move})

    @mcp.tool()
    def party_stats(pokemon: str, client_id: str | None = None) -> dict[str, Any]:
        """打开一只的能力页（之后照常按键翻页、退出）"""
        return execute("party_stats", client_id, {"pokemon": pokemon})

    @mcp.tool()
    def party_close(client_id: str | None = None) -> dict[str, Any]:
        """关上队伍列表"""
        return execute("party_close", client_id, {})
