"""真实 WebSocket 回环：flush 在先、两种问、答复缓存、取消与单连接占用。"""

import asyncio
from pathlib import Path

import pytest
from _doubles.reviewer import audit_request, inject_request
from _doubles.reviewer_link import reviewer_server
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from pokemon_agent.reviewer_link import RemoteReviewer
from pokemon_agent.schemas.harness.communication.FromHarnessToReviewerAskMsg import (
    FromHarnessToReviewerAskMsg,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToReviewerCancelMsg import (
    FromHarnessToReviewerCancelMsg,
)
from pokemon_agent.schemas.reviewer.communication import (
    FromReviewerToHarnessAnswerMsg,
    FromReviewerToHarnessHelloMsg,
)
from pokemon_agent.schemas.reviewer.interaction import AuditAnswer, InjectAnswer


def test_remote_roundtrip_flushes_before_each_question_and_preserves_context(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server:
            flushed: list[int] = []
            client = RemoteReviewer(
                server.url, flush=lambda: flushed.append(1), lost_timeout_s=0.01
            )
            try:
                request = inject_request(frames=True)
                calling = asyncio.create_task(asyncio.to_thread(client.inject, request))
                seq = await asyncio.wait_for(server.opened.get(), 3)
                assert flushed == [1]
                assert server.hub.current(seq).request.context.model_dump(
                    mode="json"
                ) == request.context.model_dump(mode="json")
                assert server.hub.submit(seq, InjectAnswer(text="原话"), "human").ok
                response = await asyncio.wait_for(calling, 3)
                assert response.text == "原话" and response.by == "human" and response.answered

                auditing = asyncio.create_task(asyncio.to_thread(client.audit, audit_request()))
                seq = await asyncio.wait_for(server.opened.get(), 3)
                assert flushed == [1, 1]
                server.hub.submit(seq, AuditAnswer(verdict="overturn", note="还没成"), "human")
                answer = await asyncio.wait_for(auditing, 3)
                assert answer.verdict == "overturn" and answer.note == "还没成"
            finally:
                await asyncio.to_thread(client.close)

    asyncio.run(scenario())


def test_same_qid_is_one_question_and_cached_answer_survives_reconnect(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server:
            wire = FromHarnessToReviewerAskMsg(qid="same", op="inject", req=inject_request())
            async with connect(server.url, proxy=None) as socket:
                assert (
                    FromReviewerToHarnessHelloMsg.model_validate_json(await socket.recv()).mode
                    == "human"
                )
                await socket.send(wire.model_dump_json())
                seq = await asyncio.wait_for(server.opened.get(), 3)
                await socket.send(wire.model_dump_json())
                server.hub.submit(seq, InjectAnswer(text="once"), "human")
                answer = FromReviewerToHarnessAnswerMsg.model_validate_json(await socket.recv())
                assert answer.qid == "same" and answer.resp.text == "once"
            await asyncio.sleep(0.01)
            async with connect(server.url, proxy=None) as socket:
                await socket.recv()
                await socket.send(wire.model_dump_json())
                replay = FromReviewerToHarnessAnswerMsg.model_validate_json(await socket.recv())
                assert replay == answer
            assert len(server.hub.history()) == 1 and server.opened.empty()

    asyncio.run(scenario())


def test_disconnect_keeps_the_same_pending_question_and_user_can_answer_while_offline(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server:
            wire = FromHarnessToReviewerAskMsg(qid="offline", op="inject", req=inject_request())
            async with connect(server.url, proxy=None) as socket:
                await socket.recv()
                await socket.send(wire.model_dump_json())
                seq = await asyncio.wait_for(server.opened.get(), 3)
            await asyncio.sleep(0.01)
            assert server.hub.current(seq) is not None
            server.hub.submit(seq, InjectAnswer(text="offline answer"), "human")
            await asyncio.sleep(0)
            async with connect(server.url, proxy=None) as socket:
                await socket.recv()
                await socket.send(wire.model_dump_json())
                answer = FromReviewerToHarnessAnswerMsg.model_validate_json(await socket.recv())
                assert answer.resp.text == "offline answer" and server.opened.empty()

    asyncio.run(scenario())


def test_cancel_is_idempotent_and_does_not_cancel_the_next_question(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server, connect(server.url, proxy=None) as socket:
            await socket.recv()
            first = FromHarnessToReviewerAskMsg(qid="first", op="inject", req=inject_request())
            await socket.send(first.model_dump_json())
            await asyncio.wait_for(server.opened.get(), 3)
            cancel = FromHarnessToReviewerCancelMsg(qid="first").model_dump_json()
            await socket.send(cancel)
            await socket.send(cancel)
            next_wire = first.model_copy(update={"qid": "next"})
            await socket.send(next_wire.model_dump_json())
            seq = await asyncio.wait_for(server.opened.get(), 3)
            assert seq == 2 and server.hub.history()[0].settle.cancelled
            await socket.send(cancel)
            server.hub.submit(seq, InjectAnswer(text="next"), "human")
            answer = FromReviewerToHarnessAnswerMsg.model_validate_json(await socket.recv())
            assert answer.qid == "next"

    asyncio.run(scenario())


def test_a_second_connection_is_rejected_with_an_occupancy_reason(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server, connect(server.url, proxy=None) as first:
            await first.recv()
            async with connect(server.url, proxy=None) as second:
                with pytest.raises(ConnectionClosed, match="已有 run"):
                    await second.recv()

    asyncio.run(scenario())


def test_changed_material_under_the_same_qid_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server, connect(server.url, proxy=None) as socket:
            await socket.recv()
            wire = FromHarnessToReviewerAskMsg(qid="immutable", op="inject", req=inject_request())
            await socket.send(wire.model_dump_json())
            await asyncio.wait_for(server.opened.get(), 3)
            wire.req.prompt = "different"
            await socket.send(wire.model_dump_json())
            with pytest.raises(ConnectionClosed, match="素材不一致"):
                await socket.recv()
            assert server.hub.current(1) is not None

    asyncio.run(scenario())


def test_closing_the_client_cancels_server_pending_and_unblocks_the_graph_thread(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server:
            client = RemoteReviewer(server.url, flush=lambda: None, lost_timeout_s=0.01)
            asking = asyncio.create_task(asyncio.to_thread(client.inject, inject_request()))
            await asyncio.wait_for(server.opened.get(), 3)

            await asyncio.to_thread(client.close)
            response = await asyncio.wait_for(asking, 3)

            assert not response.answered and response.by == "none"
            assert server.hub.current() is None and server.hub.history()[0].settle.cancelled
            await asyncio.to_thread(client.close)

    asyncio.run(scenario())


def test_binding_an_occupied_port_fails_instead_of_switching_addresses(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server:
            port = int(server.url.rsplit(":", 1)[1])
            with pytest.raises(OSError):
                await server.service.serve("127.0.0.1", port)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw", ["{broken", '{"msg":"other"}', '{"msg":"ask","qid":"x","op":"audit","req":{}}']
)
def test_bad_wire_messages_are_rejected_before_opening_a_question(tmp_path: Path, raw: str) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server, connect(server.url, proxy=None) as socket:
            await socket.recv()
            await socket.send(raw)
            with pytest.raises(ConnectionClosed, match="非法 reviewer"):
                await socket.recv()
            assert server.hub.current() is None and server.opened.empty()

    asyncio.run(scenario())


def test_flush_failure_does_not_emit_a_question(tmp_path: Path) -> None:
    async def scenario() -> None:
        def fail() -> None:
            raise OSError("trace flush failed")

        async with reviewer_server(tmp_path) as server:
            client = RemoteReviewer(server.url, flush=fail, lost_timeout_s=0.01)
            try:
                with pytest.raises(OSError, match="flush failed"):
                    await asyncio.to_thread(client.inject, inject_request())
                assert server.opened.empty()
            finally:
                await asyncio.to_thread(client.close)

    asyncio.run(scenario())


def test_wire_idempotency_outlives_the_fifty_entry_human_history(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with reviewer_server(tmp_path) as server, connect(server.url, proxy=None) as socket:
            await socket.recv()
            first = FromHarnessToReviewerAskMsg(qid="first-ever", op="inject", req=inject_request())
            for number in range(55):
                wire = first if number == 0 else first.model_copy(update={"qid": str(number)})
                await socket.send(wire.model_dump_json())
                seq = await asyncio.wait_for(server.opened.get(), 3)
                server.hub.submit(seq, InjectAnswer(text=str(number)), "human")
                await socket.recv()
            await socket.send(first.model_dump_json())
            replay = FromReviewerToHarnessAnswerMsg.model_validate_json(await socket.recv())
            assert replay.resp.text == "0" and server.opened.empty()
            assert len(server.hub.history(999)) == 50

    asyncio.run(scenario())
