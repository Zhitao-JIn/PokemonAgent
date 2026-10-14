"""memory 的 MCP 远程门面，管理面由服务端 --enable-admin 开放。

薄转发——分族分流、融合排序、kind 判别落族的实现全在 server 侧
（`memory/recall.py`，一份实现两模式共用）；本类只做信封收发。

snapshot / restore 传输 zip 内容与校验和，快照路径属于客户端一侧。
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from pokemon_agent.mcpclient.client import McpClient

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
"""原始 zip 字节上限，与服务端独立常量由测试钉等值。"""


class MemoryAdminDisabled(RuntimeError):
    """服务端未开放快照与恢复管理面。"""


class MemoryMcpTool:
    """经 MCP 调 memory server 的能力与快照管理门面。"""

    def __init__(self, client: McpClient, *, snapshot_root: Path) -> None:
        self._client = client
        self._snapshot_root = snapshot_root

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

    def _require_admin(self, name: str) -> None:
        """管理工具未注册时明确失败，不发出管理请求。"""
        if name not in self.registry:
            raise MemoryAdminDisabled("memory 服务端需用 --enable-admin 启动")

    def snapshot(self, name: str) -> Path:
        """拍快照并原子写入客户端 snapshots；调用方保证 name 是非空文件名。"""
        self._require_admin("snapshot_memory")
        assert name and Path(name).name == name, "snapshot() needs a non-empty file name"
        envelope = self._client.call_tool_sync("snapshot_memory", {"name": name})
        assert envelope["ok"], f"snapshot failed: {envelope['code']} {envelope['error']}"
        payload = envelope["data"]
        data = base64.b64decode(payload["archive_base64"], validate=True)
        if len(data) > MAX_ARCHIVE_BYTES or len(data) != payload["size"]:
            raise ValueError("snapshot archive size is invalid or exceeds MAX_ARCHIVE_BYTES")
        if hashlib.sha256(data).hexdigest() != payload["sha256"]:
            raise ValueError("snapshot archive sha256 mismatch")
        directory = self._snapshot_root / "snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{name}.zip"
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def restore(self, archive: str | Path) -> int:
        """从任意客户端 zip 路径恢复服务端记忆，返回解出的文件数。"""
        self._require_admin("restore_memory")
        path = Path(archive)
        assert path.is_file(), f"restore() needs an existing archive: {path}"
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("restore archive exceeds MAX_ARCHIVE_BYTES")
        data = path.read_bytes()
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("restore archive exceeds MAX_ARCHIVE_BYTES")
        envelope = self._client.call_tool_sync(
            "restore_memory",
            {
                "archive_base64": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
        assert envelope["ok"], f"restore failed: {envelope['code']} {envelope['error']}"
        return envelope["data"]["unpacked"]
