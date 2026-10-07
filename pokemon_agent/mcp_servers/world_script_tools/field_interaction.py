"""field_interaction 的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有签名；租约与执行由 server 注入。"""

    @mcp.tool()
    def talk_to_adjacent_npc(direction: str = "", client_id: str | None = None) -> dict[str, Any]:
        """脚本 talk_to_adjacent_npc：跟面前 NPC 说话；对话增量在 events[]，"""
        return execute("talk_to_adjacent_npc", client_id, {"direction": direction or None})

    @mcp.tool()
    def interact_facing(client_id: str | None = None) -> dict[str, Any]:
        """脚本 interact_facing：跟面前物体交互（招牌/石头/NPC 通用）；有对话→ok，"""
        return execute("interact_facing", client_id, {})

    @mcp.tool()
    def advance_dialog(max_presses: int = 30, client_id: str | None = None) -> dict[str, Any]:
        """脚本 advance_dialog：把当前对话框推进到底（反复按 a 直到回野外）；"""
        return execute("advance_dialog", client_id, {"max_presses": max_presses})
