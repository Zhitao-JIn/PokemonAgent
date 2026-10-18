"""world MCP 命令行启动：解析参数并装配真实服务。"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from pokemon_agent.world.interface.world_port import WorldPort

from .common import HEALTH_PATH, MCP_PATH

if TYPE_CHECKING:
    from pokemon_agent.world import PyBoyWorld


def main(mcp: FastMCP, start: Callable[[WorldPort, str | None], None], service_name: str) -> None:
    """提供 ROM 后启动服务；--help 在装配世界之前退出。"""
    parser = argparse.ArgumentParser(description="pokemon world MCP server")
    parser.add_argument("--rom", required=True, help="ROM 路径")
    parser.add_argument("--state-file", default=None, help="起点存档（不给 = 从开机起跑）")
    parser.add_argument("--watch", action="store_true", help="在 server 所在机器打开模拟器窗口")
    parser.add_argument(
        "--speed", type=int, default=0, help="server 所在机器的模拟器速度；0 不限速"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()

    from pokemon_agent.world import PyBoyWorld

    world = PyBoyWorld(
        args.rom,
        state_path=args.state_file,
        watch=args.watch,
        speed=args.speed,
    )
    if args.watch and args.state_file:
        world.reset(
            task_id="startup-preview",
            goal="显示配置的初始存档。",
            success_criteria="初始存档画面已载入。",
            max_steps=1,
        )
    start(world, args.rom)
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    assert mcp.settings.streamable_http_path == MCP_PATH
    print(f"{service_name} listening on http://{args.host}:{args.port}{MCP_PATH}")
    print(f"health: http://{args.host}:{args.port}{HEALTH_PATH}")
    if args.watch:
        _run_watching_server(mcp, world)
    else:
        mcp.run(transport="streamable-http")


def _run_watching_server(mcp: FastMCP, world: PyBoyWorld) -> None:
    """运行 HTTP 服务，并在同一事件循环持续泵送 SDL 消息。"""
    import uvicorn

    app = mcp.streamable_http_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        async with original_lifespan(application):
            event_pump = asyncio.create_task(_pump_window_events(world))
            try:
                yield
            finally:
                event_pump.cancel()
                with suppress(asyncio.CancelledError):
                    await event_pump

    app.router.lifespan_context = lifespan
    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    uvicorn.Server(config).run()


async def _pump_window_events(world: PyBoyWorld) -> None:
    """在 MCP 主线程每 50 毫秒处理一次 PyBoy 窗口事件。"""
    while True:
        world._pump_window_events()
        await asyncio.sleep(0.05)
