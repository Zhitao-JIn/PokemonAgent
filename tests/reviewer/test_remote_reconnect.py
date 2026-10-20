"""客户端的真实 WS 断线语义：同 qid 重发；只有已知 AI 模式能耗尽断线预算。"""

import asyncio

import pytest
from _doubles.reviewer import audit_request, inject_request
from websockets.asyncio.server import ServerConnection, serve

from pokemon_agent.reviewer_link import RemoteReviewer
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAskMsg,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.reviewer.communication import (
    FromReviewerToHarnessAnswerMsg,
    FromReviewerToHarnessHelloMsg,
)


def test_reconnect_resends_the_same_qid_and_flushes_only_once() -> None:
    async def scenario() -> None:
        qids: list[str] = []
        flushes: list[str] = []

        async def endpoint(socket: ServerConnection) -> None:
            await socket.send(FromReviewerToHarnessHelloMsg(mode="human").model_dump_json())
            request = FromHarnessToReviewerAskMsg.model_validate_json(await socket.recv())
            assert flushes == ["flushed"]
            qids.append(request.qid)
            if len(qids) == 1:
                await socket.close()
            else:
                response = FromReviewerToHarnessAnswerMsg(
                    qid=request.qid,
                    resp=FromHarnessToReviewerInjectResp(
                        text="reconnected", answered=True, by="human"
                    ),
                )
                await socket.send(response.model_dump_json())
                await socket.wait_closed()

        async with serve(endpoint, "127.0.0.1", 0) as listener:
            client = RemoteReviewer(
                f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}",
                flush=lambda: flushes.append("flushed"),
                lost_timeout_s=0.01,
            )
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(client.inject, inject_request()), 4
                )
                assert response.text == "reconnected" and len(qids) == 2 and qids[0] == qids[1]
            finally:
                await asyncio.to_thread(client.close)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode, timeout", [("human", 0.01), ("both", 0.01), ("unknown", 0.01), ("ai", None), ("ai", 0.1)]
)
@pytest.mark.parametrize("op", ["inject", "audit"])
def test_only_a_known_ai_mode_can_default_after_a_disconnect(
    mode: str, timeout: float | None, op: str
) -> None:
    async def scenario() -> None:
        arrived = asyncio.Event()

        async def endpoint(socket: ServerConnection) -> None:
            if mode != "unknown":
                await socket.send(FromReviewerToHarnessHelloMsg(mode=mode).model_dump_json())
                await socket.recv()
            arrived.set()
            await socket.wait_closed()

        listener = await serve(endpoint, "127.0.0.1", 0)
        client = RemoteReviewer(
            f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}",
            flush=lambda: None,
            lost_timeout_s=timeout,
        )
        request = inject_request() if op == "inject" else audit_request()
        asking = asyncio.create_task(asyncio.to_thread(getattr(client, op), request))
        try:
            await asyncio.wait_for(arrived.wait(), 3)
            listener.close()
            await listener.wait_closed()
            if mode == "ai" and timeout is not None:
                response = await asyncio.wait_for(asyncio.shield(asking), 2)
                assert not response.answered and response.by == "none"
                if op == "audit":
                    assert response.verdict == "accept"
            else:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(asking), 0.25)
        finally:
            await asyncio.to_thread(client.close)
            await asyncio.wait_for(asking, 3)
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())


def test_wrong_qid_is_ignored_and_a_later_matching_answer_still_wins() -> None:
    async def scenario() -> None:
        async def endpoint(socket: ServerConnection) -> None:
            await socket.send(FromReviewerToHarnessHelloMsg(mode="human").model_dump_json())
            request = FromHarnessToReviewerAskMsg.model_validate_json(await socket.recv())
            for qid, text in (("stale", "wrong"), (request.qid, "right")):
                await socket.send(
                    FromReviewerToHarnessAnswerMsg(
                        qid=qid,
                        resp=FromHarnessToReviewerInjectResp(text=text, answered=True, by="human"),
                    ).model_dump_json()
                )
            await socket.wait_closed()

        async with serve(endpoint, "127.0.0.1", 0) as listener:
            client = RemoteReviewer(
                f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}",
                flush=lambda: None,
                lost_timeout_s=0.01,
            )
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(client.inject, inject_request()), 3
                )
                assert response.text == "right"
            finally:
                await asyncio.to_thread(client.close)

    asyncio.run(scenario())


def test_wrong_answer_type_cannot_unlock_the_request_and_reconnect_keeps_its_qid() -> None:
    async def scenario() -> None:
        qids: list[str] = []

        async def endpoint(socket: ServerConnection) -> None:
            await socket.send(FromReviewerToHarnessHelloMsg(mode="human").model_dump_json())
            wire = FromHarnessToReviewerAskMsg.model_validate_json(await socket.recv())
            qids.append(wire.qid)
            wrong = FromHarnessToReviewerAuditResp(verdict="accept", answered=True, by="human")
            right = FromHarnessToReviewerInjectResp(text="right type", answered=True, by="human")
            await socket.send(
                FromReviewerToHarnessAnswerMsg(
                    qid=wire.qid, resp=wrong if len(qids) == 1 else right
                ).model_dump_json()
            )
            await socket.wait_closed()

        async with serve(endpoint, "127.0.0.1", 0) as listener:
            client = RemoteReviewer(
                f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}",
                flush=lambda: None,
                lost_timeout_s=0.01,
            )
            try:
                answer = await asyncio.wait_for(
                    asyncio.to_thread(client.inject, inject_request()), 4
                )
                assert answer.text == "right type" and qids[0] == qids[1]
            finally:
                await asyncio.to_thread(client.close)

    asyncio.run(scenario())
