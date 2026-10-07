"""field_menu 的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有签名；租约与执行由 server 注入。"""

    @mcp.tool()
    def wait_until_scene(
        scene: str, timeout_s: float = 10.0, client_id: str | None = None
    ) -> dict[str, Any]:
        """脚本 wait_until_scene：不按键只 tick，逐帧等场合变成 `scene`；超时→timeout"""
        return execute("wait_until_scene", client_id, {"scene": scene, "timeout_s": timeout_s})

    @mcp.tool()
    def open_menu_to(target: str, client_id: str | None = None) -> dict[str, Any]:
        """脚本 open_menu_to：开 start 菜单并进指定子菜单（如 POKéMON→party）；"""
        return execute("open_menu_to", client_id, {"target": target})
