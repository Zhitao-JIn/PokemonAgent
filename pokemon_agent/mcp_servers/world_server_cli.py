"""world MCP 命令行启动：解析参数并装配真实服务。"""

import argparse
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from pokemon_agent.world.interface.world_port import WorldPort

from .common import HEALTH_PATH, MCP_PATH


def main(mcp: FastMCP, start: Callable[[WorldPort, str | None], None], service_name: str) -> None:
    """提供 ROM 后启动服务；--help 在装配世界之前退出。"""
    parser = argparse.ArgumentParser(description="pokemon world MCP server")
    parser.add_argument("--rom", required=True, help="ROM 路径")
    parser.add_argument("--state-file", default=None, help="起点存档（不给 = 从开机起跑）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()

    from pokemon_agent.world import PyBoyWorld

    world = PyBoyWorld(
        args.rom,
        state_path=args.state_file,
    )
    start(world, args.rom)
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    assert mcp.settings.streamable_http_path == MCP_PATH
    print(f"{service_name} listening on http://{args.host}:{args.port}{MCP_PATH}")
    print(f"health: http://{args.host}:{args.port}{HEALTH_PATH}")
    mcp.run(transport="streamable-http")
