"""memory server：MCP 注册表暴露 memory 的能力面——`recall` / `memorize` 两个 tool。

**默认注册表只暴露能力**：任何 MCP 客户端
（agentic memory / 前端人格 agent / harness 经 mcpclient）可发现并调用的就是
这两个动作；snapshot/restore 仅在 --enable-admin 时开放，count 仍不开放。

tool 函数体是薄壳：信封组装（`common.envelope`）+ 委托 `memory.recall.MemoryCapability`
（分族分流、融合排序、kind 判别落族的**唯一实现**，进程内模式与 server 模式共用）。

起跑（用户本机，0924 口径）：

    python -m pokemon_agent.mcp_servers.memory_server --memory-root <路径>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from pokemon_agent.mcp_servers.common import (
    HEALTH_PATH,
    MAX_ARCHIVE_BYTES,
    MCP_PATH,
    envelope,
    fail,
    health_payload,
)
from pokemon_agent.memory.recall import MemoryCapability

mcp = FastMCP("pokemon-memory")

SERVICE_NAME = "pokemon-memory"
"""健康检查里报的服务名——探活时"连的是不是 memory server"一眼可辨。"""

_capability: MemoryCapability | None = None
_admin_enabled = False
_lock = threading.Lock()


def start(capability: MemoryCapability, *, enable_admin: bool = False) -> None:
    """注入能力实现（构造期一次）。tool 函数体全部经它委托。"""
    global _capability, _admin_enabled
    if _admin_enabled:
        mcp.remove_tool("snapshot_memory")
        mcp.remove_tool("restore_memory")
    _capability = capability
    _admin_enabled = enable_admin
    if enable_admin:
        mcp.tool()(snapshot_memory)
        mcp.tool()(restore_memory)


def _cap() -> MemoryCapability:
    assert _capability is not None, (
        "memory server capability not injected — call start() before serving"
    )
    return _capability


@mcp.tool()
def recall(
    query: str,
    conditions: dict[str, str] | None = None,
    limit: int | None = 8,
) -> dict[str, Any]:
    """统一回忆口：跨全部记忆族（act / task / episode / object / knowledge）检索。

    不需要指定记忆种类——给一句 query（想回忆什么）和可选的上下文 hint：
    conditions 可带 episode_id（圈本局）、map_id / place（圈某格或某图）。
    返回按相关性与 hint 命中排序的混合条目，每条自带 kind 身份。
    limit 为 null 时不截断，省略时上限为 8。
    """
    assert limit is None or limit > 0, f"limit must be > 0 or None, got {limit}"
    try:
        items = _cap().recall(query=query, conditions=conditions, limit=limit)
    except AssertionError as exc:
        return fail("rejected", str(exc))
    return envelope(data={"items": items})


@mcp.tool()
def memorize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """统一记忆口：把一批记忆写进记忆库，按每条的 kind 判别落族。

    records 每条：{"kind": "act"|"task"|"episode"|"object"|"knowledge"|"run", "payload": {...}}。
    payload 形状按 kind 对应各自 schema 的 model_dump（act=ActMemory、
    task=TaskMemory、episode=EpisodeMemory、object=ObjectFactEvent、
    knowledge={topic, content, source}）。
    返回实际落库条目（被判重跳过的不在其中）。
    """
    try:
        with _lock:
            stored = _cap().memorize(records=records)
    except AssertionError as exc:
        return fail("rejected", str(exc))
    return envelope(data={"stored": stored})


def snapshot_memory(name: str) -> dict[str, Any]:
    """返回完整 zip 内容与 sha256；名字契约或体积不满足时返回 rejected。"""
    try:
        with _lock:
            archive = _cap().snapshot(name)
            if archive.stat().st_size > MAX_ARCHIVE_BYTES:
                return fail("rejected", "snapshot archive exceeds MAX_ARCHIVE_BYTES")
            data = archive.read_bytes()
            if len(data) > MAX_ARCHIVE_BYTES:
                return fail("rejected", "snapshot archive exceeds MAX_ARCHIVE_BYTES")
    except (AssertionError, OSError) as exc:
        return fail("rejected", str(exc))
    return envelope(
        data={
            "name": name,
            "archive_base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    )


def restore_memory(archive_base64: str, sha256: str) -> dict[str, Any]:
    """校验 zip 后从根外临时文件恢复；失败返回 rejected，临时文件始终清理。"""
    try:
        if len(archive_base64) > 4 * ((MAX_ARCHIVE_BYTES + 2) // 3):
            raise ValueError("restore archive exceeds MAX_ARCHIVE_BYTES")
        data = base64.b64decode(archive_base64, validate=True)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("restore archive exceeds MAX_ARCHIVE_BYTES")
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("restore archive sha256 mismatch")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ValueError("restore archive is not a zip")
        with _lock, tempfile.TemporaryDirectory(dir=_cap().root.resolve().parent) as directory:
            archive = Path(directory) / "restore.zip"
            archive.write_bytes(data)
            unpacked = _cap().restore(archive)
    except (AssertionError, ValueError, OSError, zipfile.BadZipFile) as exc:
        return fail("rejected", str(exc))
    return envelope(data={"unpacked": unpacked})


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
            admin=_admin_enabled,
        )
    )


def main() -> None:
    """命令行入口：解析参数 → 构造能力 → 起 Streamable HTTP 服务。"""
    parser = argparse.ArgumentParser(description="pokemon memory MCP server")
    parser.add_argument("--memory-root", default=None, help="记忆库落盘根（缺省=启动目录/memory）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--enable-admin", action="store_true", help="开放快照与恢复管理工具")
    args = parser.parse_args()

    from pokemon_agent.memory import LocalEmbeddingProvider, LocalRerankerProvider

    capability = MemoryCapability(
        embedding_provider=LocalEmbeddingProvider(),
        reranker_provider=LocalRerankerProvider(),
        memory_root=args.memory_root,
    )
    start(capability, enable_admin=args.enable_admin)
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
