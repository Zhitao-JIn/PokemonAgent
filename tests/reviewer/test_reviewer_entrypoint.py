"""独立入口读取配置、跨 branch 查账与可取消终端输入；不连接真实模型服务。"""

import asyncio
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokemon_agent.reviewer import __main__ as entry
from pokemon_agent.reviewer.seats.terminal_io import StdinLines
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.trace import LocalTrace


def observation(run: str, branch: str, seq: int) -> dict:
    return {
        "output": {
            "pokemon_trace": {
                "uuid": f"event-{seq}",
                "seq": seq,
                "kind": "sense_frame",
                "type": "view",
                "started_at": 1,
                "ended_at": 2,
                "meta": {"run_id": run, "branch": branch},
                "content": {"frame": "data:image/png;base64,YQ=="},
            }
        }
    }


class Observations:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.arguments: list[dict] = []

    def get_many(self, **kwargs) -> dict:
        self.arguments.append(kwargs)
        return self.pages[len(self.arguments) - 1]


def test_langfuse_queries_all_run_branches_and_pages_before_exact_metadata_filtering() -> None:
    api = Observations(
        [
            {
                "data": [observation("r1", "main", 1), observation("other", "main", 2)],
                "meta": {"cursor": "next"},
            },
            {"data": [observation("r1", "restore-1", 3), {"output": "bad"}], "meta": {}},
        ]
    )
    client = SimpleNamespace(api=SimpleNamespace(observations=api))
    reader = entry.ConfiguredTraceReader(client=client)

    events = reader.read_events({"run_id": "r1"})

    assert [event.seq for event in events] == [1, 3]
    assert [json.loads(event.meta)["branch"] for event in events] == ["main", "restore-1"]
    assert api.arguments[0]["cursor"] is None and api.arguments[1]["cursor"] == "next"
    assert all("trace_id" not in args and "version" not in args for args in api.arguments)


def test_repeated_langfuse_cursor_is_failure_instead_of_a_partial_success() -> None:
    api = Observations([{"data": [], "meta": {"cursor": "same"}}] * 2)
    reader = entry.ConfiguredTraceReader(
        client=SimpleNamespace(api=SimpleNamespace(observations=api))
    )

    with pytest.raises(RuntimeError, match="游标重复"):
        reader.read_events({"run_id": "r1"})


def test_local_reader_does_not_bind_to_one_run_or_write_queries(tmp_path: Path) -> None:
    trace = LocalTrace(root=tmp_path)
    trace.append("view", "sense_frame", {"run_id": "old", "branch": "restore"}, {})
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    events = entry.ConfiguredTraceReader(local=trace).read_events({"run_id": "old"})

    assert len(events) == 1 and isinstance(events[0], TraceEvent)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_missing_langfuse_configuration_does_not_prevent_the_human_service_starting(
    monkeypatch, caplog
) -> None:
    def missing():
        raise RuntimeError("missing LANGFUSE keys")

    monkeypatch.setattr(entry, "build_client_from_environment", missing)
    monkeypatch.setattr(entry, "load_env_file", lambda path: None)
    monkeypatch.setattr(entry, "env_str", lambda name: None)
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(""))
    args = entry.argument_parser().parse_args(
        ["--seats", "human", "--trace-backend", "langfuse", "--url", "ws://127.0.0.1:0"]
    )

    asyncio.run(entry.run(args))

    assert "读端口未接入" in caplog.text


def test_stdin_adapter_preserves_lines_and_stops_at_eof() -> None:
    async def scenario() -> None:
        values = iter(["ctx\n", "say 原话\r\n", ""])
        lines = StdinLines(lambda: next(values))

        output = [line async for line in lines]

        assert output == ["ctx", "say 原话"]
        lines.close()

    asyncio.run(scenario())


def test_stdin_close_does_not_wait_for_the_operating_system_readline() -> None:
    async def scenario() -> None:
        entered, release = threading.Event(), threading.Event()

        def blocked() -> str:
            entered.set()
            release.wait(5)
            return ""

        lines = StdinLines(blocked)
        iterator = lines.__aiter__()
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            lines.close()
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(iterator.__anext__(), 1)
        finally:
            release.set()

    asyncio.run(scenario())


def test_stdin_errors_propagate_instead_of_becoming_an_answer() -> None:
    async def scenario() -> None:
        def fail() -> str:
            raise OSError("stdin failed")

        lines = StdinLines(fail)
        with pytest.raises(OSError, match="stdin failed"):
            async for _ in lines:
                pass
        lines.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments",
    [
        ["--seats", "ai"],
        ["--seats", "human", "--url", "http://localhost"],
        ["--seats", "human", "--trace-backend", "langfuse", "--trace-root", "irrelevant"],
    ],
)
def test_invalid_entrypoint_configuration_fails_before_serve(
    tmp_path: Path, arguments: list[str]
) -> None:
    args = entry.argument_parser().parse_args([*arguments, "--env-file", str(tmp_path / "no.env")])

    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(entry.run(args))
