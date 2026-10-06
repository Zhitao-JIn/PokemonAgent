"""mcpclient：memory / world 的门面 + MCP client（带逻辑属性）。

`tools/` 拆分的对外一半（2026-09-29 定案）：`MemoryToolPort` / `GameToolPort`
的实现住这里，底层调用换成 MCP 转发；**不持账本坐标**（三章归 harness 判定层）。
进程内模式（server_url 缺省）内部直连进程内实现——门面唯一，传输切换。

对外三件：`McpClient`（会话与转发）、`MemoryMcpTool` / `WorldMcpTool`（门面）、
`assert_mcp_server_ready`（build 前探活）。
"""

from pokemon_agent.mcpclient.client import (
    HEALTH_PATH,
    MCP_PATH,
    McpClient,
    McpToolError,
    McpTransportError,
    assert_mcp_server_ready,
    health_url,
    mcp_endpoint,
)

__all__ = [
    "HEALTH_PATH",
    "MCP_PATH",
    "McpClient",
    "McpToolError",
    "McpTransportError",
    "assert_mcp_server_ready",
    "health_url",
    "mcp_endpoint",
]
