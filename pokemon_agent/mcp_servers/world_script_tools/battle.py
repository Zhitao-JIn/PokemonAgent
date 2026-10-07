"""battle 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def battle_fight(move: str, client_id: str | None = None) -> dict[str, Any]:
        """出招：招式必须是在场宝可梦的且还有 PP；之后自动推进到下一个选单或战斗结束"""
        return execute("battle_fight", client_id, {"move": move})

    @mcp.tool()
    def battle_switch(pokemon: str, client_id: str | None = None) -> dict[str, Any]:
        """换人：换上一只没倒下、不在场的队员；对手会趁机出招"""
        return execute("battle_switch", client_id, {"pokemon": pokemon})

    @mcp.tool()
    def battle_use_item(
        item: str, pokemon: str = "", client_id: str | None = None
    ) -> dict[str, Any]:
        """用道具：扔球、给队员喝药 / 解异常 / 复活、X 系列；用掉一回合"""
        return execute("battle_use_item", client_id, {"item": item, "pokemon": pokemon})

    @mcp.tool()
    def battle_run(client_id: str | None = None) -> dict[str, Any]:
        """逃跑（只限野生宝可梦；不一定逃得掉）"""
        return execute("battle_run", client_id, {})

    @mcp.tool()
    def switch_send_out(pokemon: str, client_id: str | None = None) -> dict[str, Any]:
        """派出下一只：必须是没倒下的队员；之后自动推进到下一个选单"""
        return execute("switch_send_out", client_id, {"pokemon": pokemon})
