"""从生产 MCP 注册器读取脚本签名；不装配世界、不执行脚本。"""

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

from pokemon_agent.mcp_servers.world_script_tools.register import register


def _unused_executor(
    name: str, client_id: str | None, arguments: dict[str, str | int | float | None]
) -> dict[str, Any]:
    """签名探针不允许执行世界操作。"""
    raise RuntimeError("签名探针不执行脚本")


def public_tools() -> list[Tool]:
    """返回真实注册器的公开签名；调用方须位于同步构建或测试入口。"""
    server = FastMCP("eval-script-signatures")
    register(server, _unused_executor)
    return asyncio.run(server.list_tools())
