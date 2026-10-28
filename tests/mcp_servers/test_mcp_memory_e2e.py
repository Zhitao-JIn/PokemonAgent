"""memory server 能力面（recall / memorize）的 in-memory 端到端测试。

**钉住的事**（MCP 化定案 2026-09-29）：

1. 默认注册表仅暴露 `recall` / `memorize`；管理面只在 enable_admin 时开放；
2. `memorize` 按 kind 判别落五族（act / task / episode / object / knowledge），
   knowledge 判重（同 topic + 正文逐字）跳过；
3. `recall` 分族规则：`conditions.episode_id` 圈本局（act step 升序 + task）、
   `conditions.place` 圈格（object）、`query` 走 episode / knowledge 语义检索；
4. **双路径对齐**：经 MCP 调 server 与进程内直调 `MemoryCapability.recall`，
   同输入结果逐字段一致（一份实现两模式共用的验证）。

不连网、不碰模拟器、不调真模型（Fake embedder / reranker，全零向量）；
transport 用 SDK 的 in-memory 通道（`create_connected_server_and_client_session`）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session

from pokemon_agent.mcp_servers import memory_server
from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory


class _FakeEmbedder:
    """最小假件：全零向量（构造期不被调用）。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]


class _FakeReranker:
    """最小假件：全零分。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0] * len(documents)


# ---- 记录构造（各 kind 的最小合法 payload） ----

RUN = "r1"
EP = "e1"


def _act_payload(step: int = 1) -> dict[str, Any]:
    obs = ActMemory.Observation(facts={"overlay": "none"}, step=step)
    return ActMemory(
        before=obs,
        action="up",
        after=obs,
        step=step,
        episode_id=EP,
        run_id=RUN,
        observations=[],
        outcome=None,
    ).model_dump()


def _task_payload(task_id: str = "t1") -> dict[str, Any]:
    return TaskMemory(
        run_id=RUN,
        episode_id=EP,
        task_id=task_id,
        goal="走到草丛",
        termination="goal_done",
        reason="到达",
        steps_used=3,
        total_acts=3,
        summary="沿空地向北走到草丛边。",
        quality_score=0.5,
        quality_rationale="常规移动。",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _episode_payload() -> dict[str, Any]:
    return EpisodeMemory(
        episode_id=EP,
        run_id=RUN,
        goal="走到草丛",
        termination="goal_done",
        steps=0,
        summary="这一局走到了草丛边。",
        markdown="这一局走到了草丛边。",
        quality_score=0.5,
        quality_rationale="常规。",
        applicable_scenes=["walk"],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _object_payload(step: int = 1) -> dict[str, Any]:
    from pokemon_agent.schemas.memory.datastore.object_memory import ObjectDialogEvent

    place = ObjectDialogEvent.Place(map_id=12, x=13, y=8)
    return ObjectDialogEvent(
        outcome="dialog",
        episode_id=EP,
        step=step,
        run_id=RUN,
        place=place,
        actor_place=place,
        object_kind="人",
        button="a",
        text="你好。",
    ).model_dump()


def _knowledge_payload(
    topic: str = "草丛", text: str = "草丛里会遇到野生宝可梦。"
) -> dict[str, Any]:
    return {"topic": topic, "text": text, "source": f"{RUN}/{EP}", "run_id": RUN, "episode_id": EP}


# ---- harness：能力注入 + in-memory 通道 ----


def _build_capability(tmp_path: Any) -> MemoryCapability:
    cap = MemoryCapability(
        embedding_provider=_FakeEmbedder(),
        reranker_provider=_FakeReranker(),
        memory_root=tmp_path,
    )
    memory_server.start(cap)
    return cap


async def _with_server(
    flow: Callable[[Any], Awaitable[Any]],
) -> Any:
    """在 SDK 的 in-memory 通道里跑一个 async 流程（session 已 initialize）。"""
    async with create_connected_server_and_client_session(memory_server.mcp._mcp_server) as session:
        await session.initialize()
        return await flow(session)


async def _call(session: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    assert result.isError is False, f"{name} errored: {result.content}"
    return json.loads(result.content[0].text)


# ---- 测试 ----


def test_registry_exposes_exactly_recall_and_memorize(tmp_path):
    """注册表恰好两条能力：recall / memorize——运维（snapshot 等）不进 MCP 面。"""
    _build_capability(tmp_path)

    async def flow(session: Any) -> list[str]:
        tools = await session.list_tools()
        return sorted(t.name for t in tools.tools)

    assert asyncio.run(_with_server(flow)) == ["memorize", "recall"]


def test_memorize_dispatches_kinds_and_recall_filters_by_hint(tmp_path):
    """五 kind 各 memorize → recall 按 hint 分族命中；knowledge 判重跳过。"""
    _build_capability(tmp_path)
    records = [
        {"kind": "act", "payload": _act_payload(step=1)},
        {"kind": "act", "payload": _act_payload(step=2)},
        {"kind": "task", "payload": _task_payload()},
        {"kind": "episode", "payload": _episode_payload()},
        {"kind": "object", "payload": _object_payload(step=1)},
        {"kind": "knowledge", "payload": _knowledge_payload()},
        # 判重：同 topic + 正文逐字相同 → 跳过
        {"kind": "knowledge", "payload": _knowledge_payload()},
    ]

    async def flow(session: Any) -> None:
        body = await _call(session, "memorize", {"records": records})
        assert body["ok"] is True
        # 7 条输入、1 条判重跳过 → 落库 6 条
        assert len(body["data"]["stored"]) == 6

        # episode_id hint：act（step 升序）+ task 命中
        body = await _call(
            session, "recall", {"query": "", "conditions": {"episode_id": EP}, "limit": 8}
        )
        items = body["data"]["items"]
        kinds = [item["kind"] for item in items]
        assert "act" in kinds and "task" in kinds
        act_steps = [item["payload"]["step"] for item in items if item["kind"] == "act"]
        assert act_steps == sorted(act_steps), "act 按 step 升序"

        # place/map_id hint：object 命中
        body = await _call(
            session,
            "recall",
            {"query": "", "conditions": {"map_id": "12", "place": "12:13:8"}, "limit": 8},
        )
        assert any(item["kind"] == "object" for item in body["data"]["items"])

        # query 语义：episode / knowledge 命中
        body = await _call(session, "recall", {"query": "草丛", "conditions": {}, "limit": 8})
        kinds = {item["kind"] for item in body["data"]["items"]}
        assert "knowledge" in kinds

    asyncio.run(_with_server(flow))


def test_dual_path_alignment_capability_vs_server(tmp_path):
    """双路径对齐：进程内直调 MemoryCapability 与经 MCP 调 server 逐字段一致。"""
    capability = _build_capability(tmp_path)
    records = [
        {"kind": "act", "payload": _act_payload(step=1)},
        {"kind": "task", "payload": _task_payload()},
        {"kind": "knowledge", "payload": _knowledge_payload()},
    ]

    async def flow(session: Any) -> list[dict[str, Any]]:
        body = await _call(session, "memorize", {"records": records})
        assert body["ok"] is True
        body = await _call(
            session, "recall", {"query": "", "conditions": {"episode_id": EP}, "limit": 8}
        )
        return body["data"]["items"]

    via_mcp = asyncio.run(_with_server(flow))
    direct = capability.recall(query="", conditions={"episode_id": EP}, limit=8)

    # 同一份实现（server 只是薄壳委托 capability）——逐字段一致
    assert via_mcp == direct


def test_admin_round_trip_uses_the_same_capability_and_preserves_default_registry(tmp_path):
    """开管理面后可经 SDK 拍档回档；关闭后仍只有两条默认工具。"""
    capability = _build_capability(tmp_path)
    memory_server.start(capability, enable_admin=True)

    async def flow(session: Any) -> None:
        await _call(session, "memorize", {"records": [{"kind": "act", "payload": _act_payload(1)}]})
        snapshot = await _call(session, "snapshot_memory", {"name": "a"})
        await _call(session, "memorize", {"records": [{"kind": "act", "payload": _act_payload(2)}]})
        restored = await _call(
            session,
            "restore_memory",
            {
                "archive_base64": snapshot["data"]["archive_base64"],
                "sha256": snapshot["data"]["sha256"],
            },
        )
        assert restored["ok"]
        result = await _call(session, "recall", {"query": "", "conditions": {"episode_id": EP}})
        assert len(result["data"]["items"]) == 1

    try:
        asyncio.run(_with_server(flow))
    finally:
        memory_server.start(capability)
