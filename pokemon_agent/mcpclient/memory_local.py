"""`MemoryToolPort` 的实现：Harness 和记忆库之间那层门面。**不碰世界。**

**MCP 化收敛（2026-09-29 定案）**：本类收敛为四个方法——`recall` / `memorize`
（能力面，MCP 注册表同款）+ `snapshot_memory` / `restore_memory`（checkpoint 运维，
经 --enable-admin 开放）。原 15+ 个按种类分方法的查询/写入全部删除：调用方**不显式指定
记忆种类**，种类由产生方天然决定、由分族规则圈定（同 chooser 的统一动作掩码）。

**实现全在 `memory/recall.py` 的 `MemoryCapability`**（一份实现两模式共用：
进程内本类直调；MCP 模式 `mcp_servers/memory_server.py` 调同一份）。本类只做
信封组装：Port 信封 ↔ 能力实现的裸返回。

五族记忆的读写语义（随迁的领域规则，实现细节见 `memory/recall.py`）：

    act（单步情景）      等值筛（episode_id）+ step 数值升序
    task（一层一条）     等值筛（episode_id）+ total_acts 升序
    object（一格事件）   等值筛（map/place）+ step 数值升序
    episode（跨局摘要）  hint 等值筛（run_id/episode_id）自然序 / query 语义 rank
    knowledge（先验）    纯语义检索（BM25 + 向量 + reranker）+ 判重
"""

from __future__ import annotations

from pathlib import Path

from pokemon_agent.memory import EmbeddingProviderPort, RerankerProviderPort
from pokemon_agent.memory.recall import MemoryCapability
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
    """`MemoryToolPort` 的唯一实现。能力逻辑全在 `MemoryCapability`（一份实现
    两模式共用），本类只做信封组装——Port 信封 ↔ 能力实现的裸返回。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProviderPort,
        reranker_provider: RerankerProviderPort,
        memory_root: str | Path | None = None,
    ) -> None:
        """接好检索用的两个模型 provider 与整个记忆库的落盘根（同原口径）。

        `memory_root` 是**父目录**（`LocalMemoryStore` 在它下面建 `<kind>/`），
        缺省为进程启动目录下的 `memory/`。测试换隔离目录就传 `tmp_path`。
        """
        self._capability = MemoryCapability(
            embedding_provider=embedding_provider,
            reranker_provider=reranker_provider,
            memory_root=memory_root,
        )

    @classmethod
    def build(
        cls,
        *,
        memory_root: str | Path | None = None,
        memory_server_url: str | None = None,
    ) -> MemoryTool:
        """装配点唯一的入口。

        `memory_server_url`（MCP 化新增）：memory server 的 **base 地址**
        （`http://127.0.0.1:8766`，路径由 `mcpclient` 的协议常量拼）；
        给了 = 底层经 MCP 调 server（门面唯一，传输切换）；缺省 = 进程内直连
        （与改造前行为一致）。

        **本方法不探活**：探活是"run 开始前的一道闸"，与 Langfuse 同款放在
        装配点（`build.py::build_real`）显式打——工厂自己静默探活会让
        "为什么这次装配慢了两秒"变成看不见的事。
        """
        if memory_server_url:
            from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint
            from pokemon_agent.mcpclient.memory_tool import MemoryMcpTool

            client = McpClient(mcp_endpoint(memory_server_url))
            client.start()
            snapshot_root = Path(memory_root) if memory_root is not None else _default_root()
            return cls._from_delegate(MemoryMcpTool(client, snapshot_root=snapshot_root))

        from pokemon_agent.memory import LocalEmbeddingProvider, LocalRerankerProvider

        return cls(
            embedding_provider=LocalEmbeddingProvider(),
            reranker_provider=LocalRerankerProvider(),
            memory_root=memory_root,
        )

    @classmethod
    def _from_delegate(cls, delegate: MemoryCapability) -> MemoryTool:
        """用既有委托对象（如 MCP 远程门面）造 tool——跳过 provider 构造。"""
        tool = cls.__new__(cls)
        tool._capability = delegate
        return tool

    # ---- 能力面：统一回忆 / 统一记忆 ----

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        """统一回忆口：委托 `MemoryCapability.recall`，信封组装回 Port 类型。"""
        items = self._capability.recall(query=req.query, conditions=req.conditions, limit=req.limit)
        return FromHarnessToMemoryToolRecallResp(
            items=[FromHarnessToMemoryToolRecallItem(**item) for item in items]
        )

    def memorize(
        self, req: FromHarnessToMemoryToolMemorizeReq
    ) -> FromHarnessToMemoryToolMemorizeResp:
        """统一记忆口：委托 `MemoryCapability.memorize`，信封组装回 Port 类型。"""
        stored = self._capability.memorize(records=[record.model_dump() for record in req.records])
        return FromHarnessToMemoryToolMemorizeResp(
            stored=[FromHarnessToMemoryToolMemorizedRecord(**s) for s in stored]
        )

    # ---- 运维：快照 / 恢复（checkpoint 专用，MCP 需 --enable-admin） ----

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        """把整个记忆库打成一个 zip，返回它的路径。"""
        archive = self._capability.snapshot(req.name)
        return FromHarnessToMemoryToolSnapshotMemoryResp(archive=str(archive))

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        """用一个 zip 把记忆库还原到那一刻——以 zip 为准；单调缓存清掉。"""
        unpacked = self._capability.restore(req.archive)
        return FromHarnessToMemoryToolRestoreMemoryResp(unpacked=unpacked)
