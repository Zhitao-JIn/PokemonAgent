"""MCP client session 管理：连接 server、注册表缓存、call 转发、异常翻译。

**同步外观、异步内核**：MCP SDK 的 client 是 async 的，而 harness 全同步——
本模块在后台线程持一个事件循环，`call_tool_sync` 经
`asyncio.run_coroutine_threadsafe` 同步等待，调用方（MemoryTool / 图节点）
看不到任何 async。

**连接策略**：P1 试金石用"每次调用建连"（streamable HTTP 每次握手），简单且
无状态；性能不够时再升级为持久 session（接口不变，只换内核）。

**异常翻译**：JSON-RPC error（方法不存在、transport 断）→ `McpTransportError`；
工具执行失败（isError=true）→ `McpToolError`（带工具返回的文本）——与进程内
实现的异常语义对齐（调用方 except 的东西是稳定的）。

**地址形状**：env / 装配只给 **base**（`http://127.0.0.1:8766`）——MCP 端点与
健康检查的路径是本文件的协议常量，不在配置里重复第二遍（重复就会出现
"改了端口忘了改 health 路径"那种漂移）。

**build 前探活**：`assert_mcp_server_ready()` 打 `/health`，服务不在场或能力
没注入就地抛错——与 Langfuse（`trace/langfuse_support.py::assert_server_ready`）
同款先例：把"服务没起"挡在 run 开始之前，而不是跑一半才发现账/记忆静默丢。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

MCP_PATH = "/mcp"
"""MCP Streamable HTTP 的挂载路径（server 侧由 FastMCP 默认，见 `mcp_servers/`）。"""

HEALTH_PATH = "/health"
"""健康检查路径：**不是 MCP tool**——它是普通 HTTP 路由，不进 `tools/list`，
因此不会混进"能力面"（模型可见的工具清单）里。"""


def mcp_endpoint(base_url: str) -> str:
    """base（`http://host:port`）→ MCP 端点（`http://host:port/mcp`）。"""
    return f"{base_url.rstrip('/')}{MCP_PATH}"


def health_url(base_url: str) -> str:
    """base → 健康检查地址（`http://host:port/health`）。"""
    return f"{base_url.rstrip('/')}{HEALTH_PATH}"


def assert_mcp_server_ready(
    base_url: str,
    service: str = "mcp",
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """启动前探针：MCP server 必须可达、且能力已注入，否则抛 `McpTransportError`。

    `service` 只进报错文案（"memory / world 哪个没起"要一眼看出来）。
    返回 health 载荷（含 `version` / `ready` 等），供调用方打进日志。

    前置条件：`base_url` 非空（空 = 没配，装配点应当直接按"进程内模式"走，
    不该调到这里）。
    后置条件：`/health` 返回 200、`status == "ok"`、且 `ready` 为真——
    "进程在但能力没注入"同样是失败（那是配了一半的 server，用了才炸更晚）。
    """
    assert base_url.strip(), "assert_mcp_server_ready needs a non-empty base URL"
    import httpx

    url = health_url(base_url)
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True, trust_env=False)
    except httpx.HTTPError as error:
        raise McpTransportError(
            f"{service} MCP server 不可达（{url}）——run 开始前先把它起起来：{error}"
        ) from error
    if response.status_code != 200:
        raise McpTransportError(
            f"{service} MCP server 健康检查非 200（{url} → {response.status_code}）"
        )
    payload = response.json()
    if payload.get("status") != "ok":
        raise McpTransportError(f"{service} MCP server 健康检查未通过：{payload}")
    if not payload.get("ready"):
        raise McpTransportError(
            f"{service} MCP server 起了但能力没注入（{url} → ready=false）——"
            "server 进程没走到 start()，属于半启动状态"
        )
    return payload


class McpTransportError(RuntimeError):
    """transport/协议级失败：连不上、方法不存在、响应非法。"""


class McpToolError(RuntimeError):
    """工具执行失败（isError=true）。message 来自工具返回的文本。"""


class McpClient:
    """对一个 MCP server 的同步客户端外观。

    用法：
        client = McpClient("http://127.0.0.1:8766/mcp")
        client.start()
        result = client.call_tool_sync("recall", {"query": "...", "limit": 8})
        client.stop()
    """

    def __init__(self, server_url: str, request_timeout: float = 120.0) -> None:
        self._url = server_url
        self._timeout = request_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._registry: list[str] | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        """起后台事件循环线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mcpclient")
        self._thread.start()
        self._ready.wait(timeout=10.0)
        assert self._loop is not None, "mcpclient event loop failed to start"

    def stop(self) -> None:
        """停事件循环（幂等）。"""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    # ---- 注册表 ----

    @property
    def registry(self) -> list[str]:
        """tools/list 缓存的能力名清单（首次访问时拉取）。"""
        if self._registry is None:
            result = self.call_tool_sync("__list_tools__", {})
            self._registry = list(result["tools"])
        return self._registry

    # ---- 调用 ----

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """同步调用 server 的一个 tool，返回信封 dict。

        `__list_tools__` 是内部约定：返回注册表名清单而非信封。
        """
        assert self._loop is not None, "call start() before call_tool_sync()"
        future = asyncio.run_coroutine_threadsafe(
            self._call_remote_async(name, arguments), self._loop
        )
        return future.result(timeout=self._timeout)

    async def _call_remote_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(self._url) as (read, write, _get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            if name == "__list_tools__":
                tools = await session.list_tools()
                return {"tools": [t.name for t in tools.tools]}
            result = await session.call_tool(name, arguments)
            if result.isError:
                text = result.content[0].text if result.content else "tool error"
                raise McpToolError(text)
            if result.structuredContent is not None:
                return dict(result.structuredContent)
            if result.content and result.content[0].text:
                return dict(json.loads(result.content[0].text))
            raise McpTransportError("tool returned empty content")
