"""act_call 渲染两形：脚本形（script + args）与按键形（sequence）。"""

from __future__ import annotations

from typing import Any

from pokemon_agent.brain.interface import Action, ActionSegment

# ---- 5. act_call 渲染两形 ----


def _trace_req(action: Action, report: dict[str, Any] | None = None):
    from pokemon_agent.direct.trace import render
    from pokemon_agent.schemas.harness import (
        FromHarnessToTraceToolAppendReq,
        TraceKind,
    )

    return render, FromHarnessToTraceToolAppendReq(
        kind=TraceKind.ACT_CALL,
        meta={
            "run_id": "r",
            "branch": "main",
            "source": "act",
            "episode_id": "ep",
            "task_id": "t",
            "step": 1,
        },
        action=action,
        report=report,
    )


def test_act_call_script_form_carries_report() -> None:
    from pokemon_agent.brain.interface import ScriptCall

    render, req = _trace_req(
        Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2})),
        report={
            "ok": True,
            "code": "ok",
            "data": {"final_pos": {"x": 5, "y": 2}},
            "events": [],
            "calls": [],
        },
    )
    rendered = render.act_call(req)
    assert rendered.kind == "act_call"
    assert rendered.content["script"] == "walk_to"
    assert rendered.content["args"] == {"x": 5, "y": 2}
    assert rendered.content["ok"] == "true"  # 账本布尔 = 小写字符串
    assert rendered.content["code"] == "ok"
    assert "sequence" not in rendered.content


def test_act_call_key_form_unchanged() -> None:
    render, req = _trace_req(Action(sequence=[ActionSegment(name="up")]))
    rendered = render.act_call(req)
    assert rendered.content["sequence"] == [{"name": "up", "times": 1}]
    assert "script" not in rendered.content


def test_act_call_script_form_carries_flat_dialog() -> None:
    """真实报告是扁平的：`dialog` 在顶层，账里照样只多这一个键。"""
    from pokemon_agent.brain.interface import ScriptCall

    render, req = _trace_req(
        Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
        report={
            "ok": True,
            "code": "ok",
            "presses": 3,
            "calls": [],
            "dialog": ["第一行", "第二行"],
            "events": [],
        },
    )
    rendered = render.act_call(req)

    assert rendered.content["dialog"] == ["第一行", "第二行"]
    assert "data" not in rendered.content, "扁平报告没有 data 键，渲染不造一个"


def test_act_call_script_form_dialog_parses_back() -> None:
    """渲染 → 落盘形状 → `parse()` 回环：解析模型的 `extra="forbid"` 不挡这个新键。"""
    import json

    from pokemon_agent.brain.interface import ScriptCall
    from pokemon_agent.direct.trace import parse
    from pokemon_agent.schemas.harness import TraceEvent

    render, req = _trace_req(
        Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
        report={"ok": True, "code": "ok", "dialog": ["第一行", "第二行"], "events": []},
    )
    rendered = render.act_call(req)
    event = TraceEvent(
        uuid="u-1",
        seq=1,
        kind=rendered.kind,
        type=rendered.type,
        started_at=0.0,
        ended_at=0.0,
        meta=json.dumps(req.meta, ensure_ascii=False),
        content=json.dumps(rendered.content, ensure_ascii=False),
    )

    parsed = parse(event)

    assert parsed.content.dialog == ["第一行", "第二行"]
