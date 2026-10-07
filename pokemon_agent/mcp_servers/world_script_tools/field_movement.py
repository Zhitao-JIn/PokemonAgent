"""field_movement 的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有签名；租约与执行由 server 注入。"""

    @mcp.tool()
    def face_direction(direction: str, client_id: str | None = None) -> dict[str, Any]:
        """脚本 face_direction：转向指定方向（已面向则原地不动）。"""
        return execute("face_direction", client_id, {"direction": direction})

    @mcp.tool()
    def walk_to_adjacent(direction: str, client_id: str | None = None) -> dict[str, Any]:
        """脚本 walk_to_adjacent：向相邻格走一步；被挡 → blocked，落草丛 → entered_grass。"""
        return execute("walk_to_adjacent", client_id, {"direction": direction})

    @mcp.tool()
    def walk_to(
        x: int, y: int, max_steps: int = 200, client_id: str | None = None
    ) -> dict[str, Any]:
        """脚本 walk_to：走到目标格（固定轴序贪心，被挡换轴，5 步收敛校验；不做 BFS）。"""
        return execute("walk_to", client_id, {"x": x, "y": y, "max_steps": max_steps})

    @mcp.tool()
    def circle_walk(laps: int, extent: int = 1, client_id: str | None = None) -> dict[str, Any]:
        """脚本 circle_walk：绕圈走 laps 圈（每步断言位移、圈末回起点）。"""
        return execute("circle_walk", client_id, {"laps": laps, "extent": extent})

    @mcp.tool()
    def bounce_in_tall_grass(steps: int = 30, client_id: str | None = None) -> dict[str, Any]:
        """脚本 bounce_in_tall_grass：草丛里来回走撞怪；遇怪=battle_started（目的达成），"""
        return execute("bounce_in_tall_grass", client_id, {"steps": steps})
