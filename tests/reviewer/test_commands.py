"""命令与类型化调用等价；查询的参数和帮助由同一个模型注册表派生。"""

import asyncio
from typing import Annotated, Literal

import pytest
from _doubles.reviewer import audit_request, inject_request
from pydantic import BaseModel, Field

from pokemon_agent.reviewer.hub import Commands, Hub, query_commands
from pokemon_agent.reviewer.hub.query_commands import query_help, query_schemas
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.reviewer import (
    BrainFramesQuery,
    FrameQuery,
    RecallQuery,
    TraceQuery,
    ViewAnswer,
    ViewQuery,
)
from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    AuditAnswer,
    HistoryEntry,
    InjectAnswer,
    SubmitAck,
)


class RecordingHub:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def current(self, seq: int | None = None) -> Ask:
        return Ask(seq=1, request=inject_request())

    def submit(
        self, seq: int, answer: InjectAnswer | AuditAnswer, by: Literal["human", "agent"]
    ) -> SubmitAck:
        self.calls.append(("submit", seq, answer, by))
        return SubmitAck(ok=True, text="submitted")

    def accept_proposal(self, seq: int) -> SubmitAck:
        self.calls.append(("accept_proposal", seq))
        return SubmitAck(ok=True, text="accepted proposal")

    async def query(self, seq: int, q: ViewQuery) -> ViewAnswer:
        self.calls.append(("query", seq, q))
        return ViewAnswer(ok=True, text=q.model_dump_json())

    def context(self, seq: int, section: str | None = None) -> ViewAnswer:
        self.calls.append(("context", seq, section))
        return ViewAnswer(ok=True, text="context")

    def history(self, n: int = 10) -> list[HistoryEntry]:
        self.calls.append(("history", n))
        return []

    def discuss(self, seq: int, text: str) -> SubmitAck:
        self.calls.append(("discuss", seq, text))
        return SubmitAck(ok=False, text="没有 AI 席")


@pytest.mark.parametrize(
    "line, query",
    [
        (
            "trace --run old --episode e --task t --source act --kind act_call "
            "-n 2 --offset 3 --content-limit 10",
            TraceQuery(
                run_id="old",
                episode_id="e",
                task_id="t",
                source="act",
                kind="act_call",
                last_n=2,
                offset=3,
                content_limit=10,
            ),
        ),
        (
            'recall "a b" --run-goal badge -n 2',
            RecallQuery(query="a b", conditions={"run_goal": "badge"}, limit=2),
        ),
        ("recall --runs all", RecallQuery(conditions={"runs": "all"})),
        (
            "recall --map 1 --place door --run r1 --episode e1",
            RecallQuery(
                conditions={"map_id": "1", "place": "door", "run_id": "r1", "episode_id": "e1"}
            ),
        ),
        ("frame e1 11 --before", FrameQuery(episode_id="e1", step=11, which="before")),
        ("frame e1 11 --after", FrameQuery(episode_id="e1", step=11)),
        ("frame --latest", FrameQuery(which="latest")),
        ("brain-frames --offset 2 -n 1", BrainFramesQuery(offset=2, limit=1)),
    ],
)
def test_each_query_command_is_exactly_the_corresponding_typed_query(
    line: str, query: ViewQuery
) -> None:
    hub = RecordingHub()

    answer = asyncio.run(Commands(hub).execute(7, line))

    assert answer.ok and answer.text == query.model_dump_json()
    assert hub.calls == [("query", 7, query)]


@pytest.mark.parametrize(
    "line, expected",
    [
        ("ctx", ("context", 1, None)),
        ("ctx --section 大脑输入", ("context", 1, "大脑输入")),
        ("history -n 2", ("history", 2)),
        ('say 原文 "不配对引号', ("submit", 1, InjectAnswer(text='原文 "不配对引号'), "human")),
        (
            "overturn 还没  达成",
            ("submit", 1, AuditAnswer(verdict="overturn", note="还没  达成"), "human"),
        ),
        ('ask-ai 请核对 "这里', ("discuss", 1, '请核对 "这里')),
        ("accept-ai", ("accept_proposal", 1)),
    ],
)
def test_control_commands_delegate_with_original_text(line: str, expected: tuple) -> None:
    hub = RecordingHub()

    asyncio.run(Commands(hub).execute(1, line))

    assert hub.calls == [expected]


@pytest.mark.parametrize(
    "line",
    [
        "",
        "unknown",
        "trace -n 51",
        "trace --offset -1",
        "trace --unknown x",
        "recall --kind act",
        "recall --runs all --run r1",
        "frame --latest e1 1",
        "frame e1",
        "frame e1 1 --before --after",
        "brain-frames -n 3",
        "say   ",
        "overturn   ",
        "ok extra",
        "accept-ai extra",
        'ctx --section "unclosed',
        "history -n 0",
    ],
)
def test_invalid_commands_do_not_enter_a_business_path(line: str) -> None:
    hub = RecordingHub()

    answer = asyncio.run(Commands(hub).execute(1, line))

    assert not answer.ok and not hub.calls


def test_ok_and_wrong_kind_commands_follow_hub_arbitration() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        commands = Commands(hub)
        first = hub.open_ask(inject_request())
        assert not (await commands.execute(1, "overturn no")).ok and not first.done()
        assert (await commands.execute(1, "ok")).ok
        assert (await first).response.text == ""
        second = hub.open_ask(audit_request())
        assert not (await commands.execute(2, "say no")).ok and not second.done()
        assert (await commands.execute(2, "ok")).ok
        assert (await second).response.verdict == "accept"

    asyncio.run(scenario())


def test_help_and_query_parameters_share_the_schema_registry() -> None:
    hub = RecordingHub()

    answer = asyncio.run(Commands(hub).execute(0, "help"))
    trace = asyncio.run(Commands(hub).execute(0, "help trace"))

    assert set(query_schemas()) == {"trace", "recall", "frame", "brain-frames"}
    assert answer.ok and all(name in answer.text for name in query_schemas())
    assert trace.text == query_help("trace")
    assert "--run-goal" in answer.text and "--runs" in answer.text
    assert "maximum=50" in trace.text and not hub.calls


def test_adding_a_query_variant_automatically_adds_its_command_and_help(monkeypatch) -> None:
    class ExtraQuery(BaseModel):
        tool: Literal["read_extra"] = "read_extra"
        count: int = Field(default=1, ge=1, le=3)

    monkeypatch.setattr(
        query_commands, "ViewQuery", Annotated[TraceQuery | ExtraQuery, Field(discriminator="tool")]
    )

    query = query_commands.parse_query("extra", ["--count", "2"])

    assert isinstance(query, ExtraQuery) and query.count == 2
    assert "--count" in query_commands.query_help("extra")
    assert "maximum=3" in query_commands.query_help("extra")


def test_help_rejects_an_unknown_topic_without_entering_the_hub() -> None:
    hub = RecordingHub()

    answer = asyncio.run(Commands(hub).execute(0, "help unknown"))

    assert not answer.ok and not hub.calls
