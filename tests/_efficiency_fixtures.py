"""Typed trace examples shared by the independent efficiency scorer tests."""

from pathlib import Path

from pydantic import BaseModel

from evals.agent_short_goal_run.dataset.schemas import EvalSample, SampleStart
from evals.agent_short_goal_run.scorer.stream import RunStream
from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import (
    ActCallContent,
    EpisodeStartContent,
    EventMeta,
    RunEndContent,
    RunStartContent,
    Segment,
    SenseFrameContent,
)
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.world import Facts, PlaceInWorld, RamReadout
from pokemon_agent.world.interface import DecodedText, MenuVars


def example_sample(check_id: str | None = "map_changed") -> EvalSample:
    """A single navigation goal with a registered factual completion check."""
    return EvalSample(
        sample_id="goal",
        dataset_version="test",
        category="navigation",
        start=SampleStart(kind="state", source_state="test.state", source_sha256="unused"),
        goal="Enter a building",
        success_criteria="Map changes",
        max_steps=10,
        behavior="Walk through a door",
        check_id=check_id,
        rubric=[],
        red_lines=[],
        k_metric="pass_at_k",
        split="val",
    )


def event(kind: str, content: BaseModel, *, source: str = "task.sense") -> ParsedEvent:
    """An unstamped event; example_stream assigns stable chronological coordinates."""
    return ParsedEvent(
        uuid="pending",
        kind=kind,
        type="view",
        started_at=0,
        ended_at=0,
        meta=EventMeta(run_id="run", episode_id="episode", task_id="task", source=source),
        content=content,
    )


def frame(x: int = 1, *, map_id: int = 1, text: str = "", facing: str = "north") -> ParsedEvent:
    """Position plus decoded state; text changes represent real dialogue progress."""
    return event(
        "sense_frame",
        SenseFrameContent(
            done=False,
            place=PlaceInWorld(map_id=map_id, x=x, y=1),
            facts=Facts(map_id=map_id, facing=facing, dialog_text=text),
            ram=RamReadout(
                in_battle=False,
                covered=True,
                text_source="decode",
                menu=MenuVars(current_item=0, max_item=0, top_x=0),
                money=0,
                bag=[],
                party=[],
                decoded=DecodedText(dialog_text=text, options=[], cursor=""),
            ),
        ),
    )


def action(name: str = "right", *, script: bool = False, times: int = 1) -> ParsedEvent:
    """A recorded execution, independent of how often choose was retried."""
    content = (
        ActCallContent(script=name, args={}, ok="true", code="ok")
        if script
        else (ActCallContent(sequence=[Segment(name=name, times=times)]))
    )
    return event("act_call", content, source="act")


def example_stream(*events: ParsedEvent, complete: bool = True) -> RunStream:
    """A complete single-episode run; no simulator, service, clock or model involved."""
    start = event("run_start", RunStartContent(goals=["goal"], success_criteria=["Map changes"]))
    episode = event(
        "episode_start",
        EpisodeStartContent(
            goal_id="goal",
            goal="Enter a building",
            success_criteria="Map changes",
            max_steps=10,
        ),
    )
    end = event(
        "run_end",
        RunEndContent(
            total=1,
            succeeded=1,
            termination="goal_done",
            judge_reason="factual check",
        ),
    )
    ordered = [start, episode, *events, *([end] if complete else [])]
    for index, item in enumerate(ordered):
        item.uuid = f"event-{index}"
        item.started_at = float(index)
        item.ended_at = float(index) + 0.5
    return RunStream(ordered)


def write_trace(root: Path, stream: RunStream) -> None:
    """Write a typed example through the real on-disk envelope contract."""
    root.mkdir(parents=True)
    for index, item in enumerate(stream.events):
        raw = TraceEvent(
            uuid=item.uuid,
            seq=index,
            kind=item.kind,
            type=item.type,
            started_at=item.started_at,
            ended_at=item.ended_at,
            meta=item.meta.model_dump_json(),
            content=item.content.model_dump_json(),
        )
        (root / f"{raw.uuid}.json").write_text(raw.model_dump_json(), encoding="utf-8")
