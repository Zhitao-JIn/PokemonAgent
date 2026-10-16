"""`MemoryToolPort` 的实现：Harness 和记忆库之间那层门面。**不碰世界。**

**MCP 化收敛（2026-09-29 定案）**：本类收敛为四个方法——`recall` / `memorize`
（能力面，MCP 注册表同款）+ `snapshot_memory` / `restore_memory`（checkpoint 运维，
经 --enable-admin 开放）。原 15+ 个按种类分方法的查询/写入全部删除：调用方**不显式指定
记忆种类**，种类由产生方天然决定、由分族规则圈定（同 chooser 的统一动作掩码）。

**能力实现位于 memory server**，本类只通过 `MemoryMcpTool` 访问 MCP，
负责 Port 信封与远程能力裸返回之间的转换。

五族记忆的读写语义（随迁的领域规则，实现细节见 `memory/recall.py`）：

    act（单步情景）      等值筛（episode_id）+ step 数值升序
    task（一层一条）     等值筛（episode_id）+ total_acts 升序
    object（一格事件）   等值筛（map/place）+ step 数值升序
    episode（跨局摘要）  hint 等值筛（run_id/episode_id）自然序 / query 语义 rank
    knowledge（先验）    纯语义检索（BM25 + 向量 + reranker）+ 判重
"""

from __future__ import annotations

from pathlib import Path

from pokemon_agent.mcpclient.memory_tool import MemoryMcpTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizedRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolRestoreMemoryResp,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryResp,
)


def _default_root() -> Path:
    """缺省落盘根：**进程启动目录**下的 `memory/`（与 `memory/store.py` 同一条规矩）。"""
    return Path.cwd() / "memory"


class MemoryTool:
    """`MemoryToolPort` 的 MCP 信封适配层，能力逻辑由服务端执行。"""

    def __init__(self, client: MemoryMcpTool) -> None:
        """注入已连接的 MCP 门面；调用方负责客户端的启动与关闭。"""
        self._client = client

    @classmethod
    def build(
        cls,
        *,
        memory_server_url: str,
        memory_root: str | Path | None = None,
    ) -> MemoryTool:
        """连接 memory server；空地址抛 ValueError，传输失败向上传递。

        地址必须非空；memory_root 仅指定客户端快照根，缺省为启动目录下的 memory/。
        本方法启动客户端但不探活，装配点负责在 run 开始前检查 /health。
        """
        if not memory_server_url.strip():
            raise ValueError("memory 只经 MCP：请设置 MCP_MEMORY_SERVER_URL")

        from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint

        client = McpClient(mcp_endpoint(memory_server_url))
        client.start()
        snapshot_root = Path(memory_root) if memory_root is not None else _default_root()
        return cls(MemoryMcpTool(client, snapshot_root=snapshot_root))

    # ---- 能力面：统一回忆 / 统一记忆 ----

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        """统一回忆口：委托 `MemoryMcpTool.recall`，信封组装回 Port 类型。"""
        items = self._client.recall(query=req.query, conditions=req.conditions, limit=req.limit)
        return FromHarnessToMemoryToolRecallResp(
            items=[FromHarnessToMemoryToolRecallItem(**item) for item in items]
        )

    def memorize(
        self, req: FromHarnessToMemoryToolMemorizeReq
    ) -> FromHarnessToMemoryToolMemorizeResp:
        """统一记忆口：委托 `MemoryMcpTool.memorize`，信封组装回 Port 类型。"""
        stored = self._client.memorize(records=[record.model_dump() for record in req.records])
        return FromHarnessToMemoryToolMemorizeResp(
            stored=[FromHarnessToMemoryToolMemorizedRecord(**s) for s in stored]
        )

    # ---- 运维：快照 / 恢复（checkpoint 专用，MCP 需 --enable-admin） ----

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        """把整个记忆库打成一个 zip，返回它的路径。"""
        archive = self._client.snapshot(req.name)
        return FromHarnessToMemoryToolSnapshotMemoryResp(archive=str(archive))

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        """用一个 zip 把记忆库还原到那一刻——以 zip 为准；单调缓存清掉。"""
        unpacked = self._client.restore(req.archive)
        return FromHarnessToMemoryToolRestoreMemoryResp(unpacked=unpacked)
