"""A3 后端 × agent：起真后端 + 一个**假** agent WS 服务，验证跳 C 收发与 settle.by 三分支。

覆盖：backend 经跳 C 把 `seed` 发给 agent；agent 推回的 `proposal` 被转成跳 B `ProposalReq`
广播给 `/ui`；「发给 AI」触发跳 C `turn`；settle 的 `by` 三分支（human / agent / timeout）；
settle 后向 agent 发 `close`。
"""

from __future__ import annotations

import asyncio
import json

from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve

from pokemon_agent.review_backend import AgentClient, ReviewBackend
from pokemon_agent.schemas.agent_reviewer.communication import (
    CloseReq,
    ProposalMsg,
    SeedReq,
    TurnReq,
)
from pokemon_agent.schemas.harness import FromHarnessToReviewBackendInjectReq
from pokemon_agent.schemas.review_backend import (
    FromFrontendToReviewBackendAnswerReq,
    FromFrontendToReviewBackendDiscussReq,
    ProposedAnswer,
)


class _FakeAgent:
    """假 agent：收到 seed/turn 各回一笔固定 proposal，close 只记录。"""

    def __init__(self) -> None:
        self.seeds: list[SeedReq] = []
        self.turns: list[TurnReq] = []
        self.closes: list[CloseReq] = []

    async def handler(self, conn) -> None:
        async for raw in conn:
            data = json.loads(raw)
            msg = data.get("msg")
            if msg == "seed":
                req = SeedReq.model_validate(data)
                self.seeds.append(req)
                await conn.send(
                    ProposalMsg(
                        seq=req.seq, proposal=ProposedAnswer(text="agent-seed"), round=0
                    ).model_dump_json()
                )
            elif msg == "turn":
                req = TurnReq.model_validate(data)
                self.turns.append(req)
                await conn.send(
                    ProposalMsg(
                        seq=req.seq, proposal=ProposedAnswer(text="agent-turn"), round=0
                    ).model_dump_json()
                )
            elif msg == "close":
                self.closes.append(CloseReq.model_validate(data))


async def _one_round(ui, h, answer_json: str) -> dict:
    """走完一问：harness 发 inject → 收 ask → 收 proposal → UI 答 → 收 harness resp + settle。

    UI 发答案后会先收到 `answer_ack`，再收到 `settle`；harness 收到回话。
    """
    await h.send(
        FromHarnessToReviewBackendInjectReq(
            run_id="r", prompt="p", form_kind="F", form_text="{}", timeout_s=5
        ).model_dump_json()
    )
    ask = json.loads(await asyncio.wait_for(ui.recv(), 5))
    assert ask["msg"] == "ask"
    # agent 应已收到 seed
    await asyncio.sleep(0.1)
    prop = json.loads(await asyncio.wait_for(ui.recv(), 5))
    assert prop["msg"] == "proposal" and prop["round"] == 0
    await ui.send(answer_json)
    ack = json.loads(await asyncio.wait_for(ui.recv(), 5))  # answer_ack
    assert ack["msg"] == "answer_ack"
    resp = json.loads(await asyncio.wait_for(h.recv(), 5))  # harness 回话
    assert "seq" in resp
    settle = json.loads(await asyncio.wait_for(ui.recv(), 5))  # settle
    assert settle["msg"] == "settle"
    return settle


async def _scenario() -> None:
    agent_state = _FakeAgent()
    async with serve(agent_state.handler, "127.0.0.1", 0) as agent_server:
        agent_port = next(iter(agent_server.sockets)).getsockname()[1]
        agent_client = AgentClient(f"ws://127.0.0.1:{agent_port}")
        backend = ReviewBackend(agent_client=agent_client)
        async with backend.serve("127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            base = f"127.0.0.1:{port}"
            await backend.start_agent()
            assert backend._agent is not None and backend._agent.connected
            # 连不上才降级；这里应连上
            assert len(agent_state.seeds) == 0

            ui = await ws_connect(f"ws://{base}/ui", proxy=None)
            h = await ws_connect(f"ws://{base}/harness", proxy=None)

            # 分支 1：agent 模式、填内容 → by=agent
            s1 = await _one_round(
                ui,
                h,
                FromFrontendToReviewBackendAnswerReq(
                    seq=1, by="agent", text="ok"
                ).model_dump_json(),
            )
            assert s1["by"] == "agent"

            # 分支 2：human 模式、填内容 → by=human
            s2 = await _one_round(
                ui,
                h,
                FromFrontendToReviewBackendAnswerReq(
                    seq=2, by="human", text="fine"
                ).model_dump_json(),
            )
            assert s2["by"] == "human"

            # 分支 3：agent 模式、空框 → by=timeout
            s3 = await _one_round(
                ui,
                h,
                FromFrontendToReviewBackendAnswerReq(seq=3, by="agent", text="").model_dump_json(),
            )
            assert s3["by"] == "timeout"

            # 三问各发了一次 seed + 一次 close
            assert len(agent_state.seeds) == 3
            assert len(agent_state.closes) == 3

            # 「发给 AI」：第 4 问后发 discuss → 触发跳 C turn + 新一轮 proposal
            await h.send(
                FromHarnessToReviewBackendInjectReq(
                    run_id="r", prompt="p", form_kind="F", form_text="{}", timeout_s=5
                ).model_dump_json()
            )
            ask4 = json.loads(await asyncio.wait_for(ui.recv(), 5))
            assert ask4["msg"] == "ask"
            await asyncio.sleep(0.1)
            prop4 = json.loads(await asyncio.wait_for(ui.recv(), 5))
            assert prop4["msg"] == "proposal"
            await ui.send(
                FromFrontendToReviewBackendDiscussReq(
                    seq=ask4["seq"], text="再想想"
                ).model_dump_json()
            )
            await asyncio.sleep(0.1)
            assert len(agent_state.turns) == 1
            prop4b = json.loads(await asyncio.wait_for(ui.recv(), 5))
            assert prop4b["msg"] == "proposal" and prop4b["round"] == 1

            await ui.close()
            await h.close()


def test_backend_with_agent() -> None:
    asyncio.run(_scenario())


async def _degrade_scenario() -> None:
    """`.env`/agent 没起时 AgentClient 连不上 → 后端降级为无 agent，run 照跑。"""
    agent_client = AgentClient("ws://127.0.0.1:1")  # 没服务，必然连不上
    backend = ReviewBackend(agent_client=agent_client)
    async with backend.serve("127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        base = f"127.0.0.1:{port}"
        await backend.start_agent()
        assert backend._agent is None  # 已降级
        ui = await ws_connect(f"ws://{base}/ui", proxy=None)
        h = await ws_connect(f"ws://{base}/harness", proxy=None)
        await h.send(
            FromHarnessToReviewBackendInjectReq(
                run_id="r", prompt="p", form_kind="F", form_text="{}", timeout_s=5
            ).model_dump_json()
        )
        ask = json.loads(await asyncio.wait_for(ui.recv(), 5))
        assert ask["msg"] == "ask" and ask["deadline"] is None
        # 人模式：填内容答 → by=human
        await ui.send(
            FromFrontendToReviewBackendAnswerReq(seq=ask["seq"], text="ok").model_dump_json()
        )
        ack = json.loads(await asyncio.wait_for(ui.recv(), 5))
        assert ack["msg"] == "answer_ack"
        resp = json.loads(await asyncio.wait_for(h.recv(), 5))
        assert "seq" in resp
        settle = json.loads(await asyncio.wait_for(ui.recv(), 5))
        assert settle["by"] == "human"
        await ui.close()
        await h.close()


def test_backend_degrades_without_agent() -> None:
    asyncio.run(_degrade_scenario())
