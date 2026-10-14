"""读侧解析层的用法示范：落盘账本 → `parse()` → 类型化事件，写与读逐字段对得上。

`direct/trace/content.py` 是 `render.py` 的镜像；两边任何一边改了字段名，这里当场红。
样本有两份：`_fake_run` 用真的三张图跑出来的整局账本（覆盖面），以及一条带内存读数的
`sense_frame`（`ram` 是测评读真值的唯一来源，单独回环一次）。
"""

from __future__ import annotations

from _fake_run import run_fake

from pokemon_agent.direct.trace import CONTENT_MODELS, TraceTool, parse
from pokemon_agent.direct.trace.content import (
    OtherContent,
    SenseFrameContent,
    TaskEndContent,
)
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceEvent, TraceKind
from pokemon_agent.world import Facts, Observation, RamReadout
from pokemon_agent.world.interface import (
    BagItem,
    BattleStatus,
    Combatant,
    DecodedText,
    MenuVars,
    PartyMon,
)


def test_every_modelled_account_of_a_whole_run_parses_into_its_model(tmp_path) -> None:
    runs = [
        run_fake(tmp_path / "normal", checkpoints=True),
        run_fake(tmp_path / "task_error", fail_on_press=2, run=lambda asked: True),
        run_fake(tmp_path / "episode_error", fail_on_decompose=1, run=lambda asked: True),
    ]
    events = [TraceEvent.model_validate(e) for run in runs for e in run]

    parsed = [parse(e) for e in events]

    modelled = [p for p in parsed if p.kind in CONTENT_MODELS]
    assert modelled, "整局账本里一条建过模的账都没有"
    for p in modelled:
        assert isinstance(p.content, CONTENT_MODELS[p.kind]), p.kind
        assert not isinstance(p.content, OtherContent)
    ends = [p.content for p in parsed if p.kind == TraceKind.TASK_END]
    assert ends and all(isinstance(c, TaskEndContent) for c in ends)
    assert all(isinstance(c.steps_used, int) for c in ends), "标量读回来是真实类型，不是字符串"


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
            obs=Observation(step=3, status="s", facts=facts),
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
