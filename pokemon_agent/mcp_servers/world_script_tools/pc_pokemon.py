"""pc_pokemon 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def pc_withdraw_pokemon(pokemon: str, client_id: str | None = None) -> dict[str, Any]:
        """从当前箱取一只到队伍（队伍满 6 只不能取）"""
        return execute("pc_withdraw_pokemon", client_id, {"pokemon": pokemon})

    @mcp.tool()
    def pc_deposit_pokemon(pokemon: str, client_id: str | None = None) -> dict[str, Any]:
        """把队伍里的一只存进当前箱（队伍只剩一只不能存）"""
        return execute("pc_deposit_pokemon", client_id, {"pokemon": pokemon})

    @mcp.tool()
    def pc_change_box(n: int, client_id: str | None = None) -> dict[str, Any]:
        """换当前箱（游戏会存一次档）"""
        return execute("pc_change_box", client_id, {"n": n})

    @mcp.tool()
    def pc_log_off(client_id: str | None = None) -> dict[str, Any]:
        """关上 PC"""
        return execute("pc_log_off", client_id, {})
