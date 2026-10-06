"""memory server：MCP 注册表暴露 memory 的能力面——`recall` / `memorize` 两个 tool。

**注册表只暴露能力，不暴露存储原语**（用户定案 2026-09-29）：任何 MCP 客户端
（agentic memory / 前端人格 agent / harness 经 mcpclient）可发现并调用的就是
这两个动作；运维（snapshot/restore/count）不进 MCP 面，走本模块的启动参数与
本地管理。

tool 函数体是薄壳：信封组装（`common.envelope`）+ 委托 `memory.recall.MemoryCapability`
（分族分流、融合排序、kind 判别落族的**唯一实现**，进程内模式与 server 模式共用）。

起跑（用户本机，0924 口径）：

    python -m pokemon_agent.mcp_servers.memory_server --memory-root <路径>
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from pokemon_agent.mcp_servers.common import HEALTH_PATH, MCP_PATH, envelope, fail, health_payload
from pokemon_agent.memory.recall import MemoryCapability

mcp = FastMCP("pokemon-memory")

SERVICE_NAME = "pokemon-memory"
"""健康检查里报的服务名——探活时"连的是不是 memory server"一眼可辨。"""

_capability: MemoryCapability | None = None


def start(capability: MemoryCapability) -> None:
    """注入能力实现（构造期一次）。tool 函数体全部经它委托。"""
    global _capability
    _capability = capability


def _cap() -> MemoryCapability:
    assert _capability is not None, (
        "memory server capability not injected — call start() before serving"
    )
    return _capability


@mcp.tool()
def recall(
    query: str,
    conditions: dict[str, str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """统一回忆口：跨全部记忆族（act / task / episode / object / knowledge）检索。

    不需要指定记忆种类——给一句 query（想回忆什么）和可选的上下文 hint：
    conditions 可带 episode_id（圈本局）、map_id / place（圈某格或某图）。
    返回按相关性与 hint 命中排序的混合条目，每条自带 kind 身份。
    """
    assert limit > 0, f"limit must be > 0, got {limit}"
    try:
        items = _cap().recall(query=query, conditions=conditions, limit=limit)
    except AssertionError as exc:
        return fail("rejected", str(exc))
    return envelope(data={"items": items})


@mcp.tool()
def memorize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """统一记忆口：把一批记忆写进记忆库，按每条的 kind 判别落族。

    records 每条：{"kind": "act"|"task"|"episode"|"object"|"knowledge", "payload": {...}}。
    payload 形状按 kind 对应各自 schema 的 model_dump（act=ActMemory、
    task=TaskMemory、episode=EpisodeMemory、object=ObjectFactEvent、
    knowledge={topic, content, source}）。
    返回实际落库条目（被判重跳过的不在其中）。
    """
    try:
        stored = _cap().memorize(records=records)
    except AssertionError as exc:
        return fail("rejected", str(exc))
    return envelope(data={"stored": stored})


@mcp.custom_route(HEALTH_PATH, methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """健康检查（**普通 HTTP，不是 MCP tool**）：探活与运维用。

    200 且 `ready=true` 才是"可用"；能力没注入时 `ready=false`——探活端
    （`mcpclient.assert_mcp_server_ready`）据此把半启动状态挡在 run 之前。
    """
    capability = _capability
    return JSONResponse(
        health_payload(
            SERVICE_NAME,
            ready=capability is not None,
            root=str(capability.root) if capability is not None else None,
            transport=MCP_PATH,
        )
    )


def main() -> None:
    """命令行入口：解析参数 → 构造能力 → 起 Streamable HTTP 服务。"""
    parser = argparse.ArgumentParser(description="pokemon memory MCP server")
    parser.add_argument("--memory-root", default=None, help="记忆库落盘根（缺省=启动目录/memory）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    from pokemon_agent.memory import LocalEmbeddingProvider, LocalRerankerProvider

    capability = MemoryCapability(
        embedding_provider=LocalEmbeddingProvider(),
        reranker_provider=LocalRerankerProvider(),
        memory_root=args.memory_root,
    )
    start(capability)
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    assert mcp.settings.streamable_http_path == MCP_PATH, (
        f"FastMCP 的 streamable 路径变了（{mcp.settings.streamable_http_path} != {MCP_PATH}）"
        "——探活地址与挂载路径是两处常量，这里对不上就说明有一处没同步"
    )
    print(f"{SERVICE_NAME} listening on http://{args.host}:{args.port}{MCP_PATH}")
    print(f"health: http://{args.host}:{args.port}{HEALTH_PATH}")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
