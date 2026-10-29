"""memory 的 MCP 远程能力门面。

薄转发——分族分流、融合排序、kind 判别落族的实现全在 server 侧
（`memory/recall.py`，一份实现两模式共用）；本类只做信封收发。

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pokemon_agent.mcpclient.client import McpClient


class MemoryMcpTool:
    """经 MCP 调 memory server 的能力门面。"""

    def __init__(self, client: McpClient, *, snapshot_root: Path | None = None) -> None:
        self._client = client

    @property
    def registry(self) -> list[str]:
        """server 注册表暴露的能力名清单。"""
        return self._client.registry

    def recall(
        self,
        query: str,
        conditions: dict[str, str] | None = None,
        limit: int | None = 8,
    ) -> list[dict[str, Any]]:
        """统一回忆口：返回混合条目；limit 为 null 时不截断，省略时上限为 8。"""
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
