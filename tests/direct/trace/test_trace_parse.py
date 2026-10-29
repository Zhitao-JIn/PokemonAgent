"""读侧解析层的用法示范：落盘账本 → `parse()` → 类型化事件，写与读逐字段对得上。

`direct/trace/content.py` 是 `render.py` 的镜像；两边任何一边改了字段名，这里当场红。
覆盖面来自一个正常整局账本（`_fake_run` 跑真的三张图）加上手工补的两种异常账
（`task_error` / `episode_error`，只有异常 run 才产）；另有一条带内存读数的
`sense_frame`（`ram` 是测评读真值的唯一来源，单独回环一次）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _fake_langfuse import FakeLangfuseClient
from _fake_run import run_fake

from pokemon_agent.direct.trace import CONTENT_MODELS, TraceTool, parse
from pokemon_agent.direct.trace.content import (
    ErrorEndContent,
    OtherContent,
    SenseFrameContent,
    TaskEndContent,
)
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceEvent, TraceKind
from pokemon_agent.trace import LangfuseTrace
from pokemon_agent.world import (
    Facts,
    Observation,
    PlaceInWorld,
    RamReadout,
    TaskObservation,
    TaskScene,
)
from pokemon_agent.world.interface import (
    BagItem,
    BattleStatus,
    Combatant,
    DecodedText,
    MenuVars,
    PartyMon,
)


def test_every_modelled_account_of_a_whole_run_parses_into_its_model(tmp_path) -> None:
    """正常整局的建模账都读成它的模型；差集（只有异常 run 才产的账）手工补最小事件覆盖。"""
    run = run_fake(tmp_path / "normal")
    events = [TraceEvent.model_validate(e) for e in run]

    parsed = [parse(e) for e in events]

    modelled = [p for p in parsed if p.kind in CONTENT_MODELS]
    assert modelled, "整局账本里一条建过模的账都没有"
    for p in modelled:
        assert isinstance(p.content, CONTENT_MODELS[p.kind]), p.kind
        assert not isinstance(p.content, OtherContent)
    ends = [p.content for p in parsed if p.kind == TraceKind.TASK_END]
    assert ends and all(isinstance(c, TaskEndContent) for c in ends)
    assert all(isinstance(c.steps_used, int) for c in ends), "标量读回来是真实类型，不是字符串"

    # 差集（3-run 并集 − 正常 run = {task_error, episode_error}）手工补最小事件，
    # 保证原先被异常 run 覆盖的每种建模账仍被覆盖。
    normal_modelled = {p.kind for p in modelled}
    extra = [
        TraceEvent(
            uuid="te",
            seq=1,
            kind=TraceKind.TASK_ERROR,
            type="lifecycle",
            started_at=1.0,
            ended_at=1.0,
            meta=json.dumps({"run_id": "r1"}),
            content=json.dumps({"error": "boom"}),
        ),
        TraceEvent(
            uuid="ee",
            seq=1,
            kind=TraceKind.EPISODE_ERROR,
            type="lifecycle",
            started_at=1.0,
            ended_at=1.0,
            meta=json.dumps({"run_id": "r1"}),
            content=json.dumps({"error": "boom"}),
        ),
    ]
    for event in extra:
        assert event.kind not in normal_modelled, f"{event.kind} 正常 run 也产，不属于差集"
        parsed_extra = parse(event)
        assert isinstance(parsed_extra.content, ErrorEndContent)
        assert not isinstance(parsed_extra.content, OtherContent)


def test_a_sense_frame_with_a_ram_readout_round_trips(tmp_path) -> None:
    ram = RamReadout(
        in_battle=True,
        covered=True,
        text_source="decode",
        menu=MenuVars(current_item=1, max_item=1, top_x=15),
        money=3000,
        bag=[BagItem(item_id=0x14, quantity=1)],
        party=[PartyMon(species=153, level=5, hp=20, max_hp=20, status="ok")],
        battle=BattleStatus(
            mine=Combatant(name="BULBASAUR", level=5, hp=20, max_hp=20, status="ok"),
            foe=Combatant(name="RATTATA", level=3, hp=9, max_hp=15, status="PSN"),
        ),
        decoded=DecodedText(dialog_text="", options=["FIGHT", "PKMN"], cursor="FIGHT"),
    )
    facts = Facts(
        scene=None, overlay=Facts.Overlay.CHOICE, options=["FIGHT", "PKMN"], my_hp="20/20"
    )
    trace = TraceTool.build(run_id="r1", trace_root=tmp_path)
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": "task.sense", "episode_id": "r1-ep1", "task_id": "t1", "step": 3},
            obs=Observation(step=3, facts=facts),
            frame="data:image/png;base64,AAAA",
            ram=ram,
        )
    )

    [event] = trace.read_events({"run_id": "r1"})
    parsed = parse(event)

    assert isinstance(parsed.content, SenseFrameContent)
    assert parsed.content.ram == ram
    assert parsed.content.facts.options == ["FIGHT", "PKMN"]
    assert parsed.content.facts.model_extra == {"my_hp": "20/20"}
    assert parsed.content.done is False and parsed.meta.step == 3


@pytest.mark.parametrize("backend", ["local", "langfuse"])
def test_a_status_written_by_an_old_run_still_parses_but_new_ones_stop_writing_it(
    tmp_path: Path, backend: str
) -> None:
    facts = Facts(overlay=Facts.Overlay.CHOICE, options=["FIGHT"], my_hp="20/20")
    observation = TaskObservation(
        step=0, facts=facts, scene=TaskScene.BATTLE, place=PlaceInWorld(map_id=1, x=2, y=3)
    )
    if backend == "local":
        trace = TraceTool.build(run_id="r1", trace_root=tmp_path)
    else:
        client = FakeLangfuseClient()
        trace = TraceTool(
            LangfuseTrace(trace_id=client.create_trace_id(seed="r1"), client=client), run_id="r1"
        )

    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": "task.sense", "episode_id": "r1-ep1", "task_id": "t1", "step": 0},
            obs=observation,
        )
    )
    [event] = trace.read_events({"run_id": "r1"})
    written = json.loads(event.content)
    current = parse(event)
    old = event.model_copy(
        update={"content": json.dumps({**written, "status": "旧状态"}, ensure_ascii=False)}
    )
    previous = parse(old)

    assert set(written) == {"facts", "done", "scene", "place"}
    assert written["facts"] == facts.model_dump(mode="json")
    assert current.content.status is None
    assert current.content.scene == observation.scene
    assert current.content.place == observation.place
    assert current.content.facts.overlay == Facts.Overlay.CHOICE
    assert isinstance(previous.content, SenseFrameContent)
    assert previous.content.status == "旧状态"
    assert previous.content.model_dump(exclude={"status"}) == current.content.model_dump(
        exclude={"status"}
    )
