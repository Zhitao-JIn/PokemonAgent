"""memory 能力面的 MCP 远程门面：`recall` / `memorize` 两方法。

薄转发——分族分流、融合排序、kind 判别落族的实现全在 server 侧
（`memory/recall.py`，一份实现两模式共用）；本类只做信封收发。

**MemoryToolPort 收敛前的过渡**：`MemoryToolPort`（15+ 方法）收敛为 recall /
memorize 两方法是 P1 后半（全仓调用点改造）；收敛完成前本类以独立类存在，
收敛后它成为 `MemoryToolPort` 的 MCP 实现。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.mcpclient.client import McpClient


class MemoryMcpTool:
    """经 MCP 调 memory server 的统一回忆 / 统一记忆门面。"""

    def __init__(self, client: McpClient) -> None:
        self._client = client

    @property
    def registry(self) -> list[str]:
        """server 注册表暴露的能力名清单。"""
        return self._client.registry

    def recall(
        self,
        query: str,
        conditions: dict[str, str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """统一回忆口：返回混合条目 `[{kind, uuid, score, content, payload}]`。"""
        envelope = self._client.call_tool_sync(
            "recall", {"query": query, "conditions": conditions, "limit": limit}
        )
        assert envelope["ok"], f"recall failed: {envelope['code']} {envelope['error']}"
        return envelope["data"]["items"]

    def memorize(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """统一记忆口：返回实际落库条目 `[{"kind", "uuid"}]`（判重跳过的不在）。"""
        envelope = self._client.call_tool_sync("memorize", {"records": records})
        assert envelope["ok"], f"memorize failed: {envelope['code']} {envelope['error']}"
        return envelope["data"]["stored"]
