"""learn 场合的显式 MCP 脚本 API。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册现有脚本签名；执行、租约和报告由注入回调处理。"""

    @mcp.tool()
    def learn_forget(move: str, client_id: str | None = None) -> dict[str, Any]:
        """忘掉一招、学新招（秘传招式忘不掉）"""
        return execute("learn_forget", client_id, {"move": move})

    @mcp.tool()
    def learn_skip(client_id: str | None = None) -> dict[str, Any]:
        """不学这招"""
        return execute("learn_skip", client_id, {})
