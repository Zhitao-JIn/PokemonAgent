"""无文案的原生动作空间经版本模板保持旧模型输入。"""

import json
from pathlib import Path

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import ACTION_LIMITS, call_policy

from pokemon_agent.brain import Brain, Goal
from pokemon_agent.direct.brain_tool import Chooser, decide_prompt_params
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.mcpclient.action_space import action_space_for
from pokemon_agent.prompt import DecideActionRetryParams, PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world import ActionSpace, Facts, PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import NamingView

from .golden_cases import GoldenCase, active_version, parse_request

GOLDEN = Path(__file__).parent / "golden"


def native_request(
    overlay: Facts.Overlay, covered: bool = False, script_only: bool = False
) -> FromHarnessToBrainToolChooseOnceReq:
    place = PlaceInWorld(map_id=1, x=2, y=3)
    observation = TaskObservation(
        step=0,
        place=place,
        scene=TaskScene.NAMING
        if covered
        else TaskScene.DIALOG
        if overlay == Facts.Overlay.DIALOG
        else TaskScene.WALK,
        takeover=NamingView(target="YOUR NAME?", typed="R") if covered else None,
        facts=Facts(
            overlay=overlay,
            where=f"全局坐标 地图{place.map_id} x={place.x} y={place.y}",
            dialog_text="欢迎" if overlay == Facts.Overlay.DIALOG else "",
            options=["YES", "NO"] if overlay == Facts.Overlay.CHOICE else [],
            cursor="YES" if overlay == Facts.Overlay.CHOICE else None,
        ),
    )
    space = action_space_for(observation, ["up", "down", "left", "right", "a", "b", "start"])
    if script_only:
        space = space.model_copy(
            update={
                "names": [],
                "mask": {
                    name: enabled if name not in space.names else False
                    for name, enabled in space.mask.items()
                },
            }
        )
    return FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="完成当前操作", criteria="操作完成")],
        obs=observation,
        space=space,
        memories=[],
        human_note="先核对",
    )


@pytest.mark.parametrize("overlay", list(Facts.Overlay))
@pytest.mark.parametrize("covered", [False, True])
def test_native_action_space_renders_overlay_help_without_display_fields(
    overlay: Facts.Overlay, covered: bool
) -> None:
    req = native_request(overlay, covered)

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert {"descriptions", "note", "map_note"}.isdisjoint(req.space.model_dump())
    assert f"- covered_by_script: {str(covered).lower()}" in actual.text
    assert f"- overlay: {overlay.value}" in actual.text
    assert "先核对" in actual.text
    assert "- up:" in actual.text
    assert ("这一屏 10 列" in actual.text) is (not covered)
    if covered:
        assert "YOUR NAME?" in actual.text
    elif overlay == Facts.Overlay.DIALOG:
        assert "- dialog_text: 欢迎" in actual.text
    elif overlay == Facts.Overlay.CHOICE:
        assert "YES" in actual.text and "NO" in actual.text


def test_a_script_only_action_space_lists_scripts_without_basic_keys() -> None:
    req = native_request(Facts.Overlay.NONE, covered=True, script_only=True)

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert "YOUR NAME?" in actual.text
    assert "## 可用动作" in actual.text
    scripts = [entry for entry in req.space.entries if req.space.mask.get(entry.name)]
    assert scripts
    assert all(entry.name in actual.text for entry in scripts)
    assert "基础按键：" not in actual.text
    assert req.space.names == []


def test_frozen_action_space_ignores_retired_display_keys() -> None:
    path = sorted((GOLDEN / "decide_action").glob("history-*.req.json"))[0]
    raw = json.loads(path.read_bytes())["request"]["space"]

    space = ActionSpace.model_validate(raw)

    assert space.model_dump(mode="json") == {
        key: value for key, value in raw.items() if key not in {"descriptions", "note", "map_note"}
    }
    assert {"descriptions", "note", "map_note"}.isdisjoint(ActionSpace.model_fields)
    assert space.model_extra is None


@pytest.mark.parametrize(
    "path", sorted((GOLDEN / "retry_prompt").glob("*.req.json")), ids=lambda path: path.stem
)
def test_retry_template_keeps_the_captured_bytes(path: Path) -> None:
    case = GoldenCase.model_validate_json(path.read_bytes())
    params = DecideActionRetryParams.model_validate(case.request)

    actual = PromptGateway(None).render("decide_action_retry", params)

    expected = path.with_name(path.name.removesuffix(".req.json") + ".prompt.txt").read_bytes()
    assert actual.text.encode("utf-8") == expected
    assert actual.task == "decide_action_retry"


@pytest.mark.parametrize("exhausted", [False, True])
def test_real_choose_attempts_are_stamped_before_success_or_exhaustion(exhausted: bool) -> None:
    req = native_request(Facts.Overlay.NONE)
    provider = ScriptedLLM(
        text_reply("invalid"), text_reply("invalid" if exhausted else '{"action":"up"}')
    )
    chooser = Chooser(
        Brain(decide_llm=provider),
        policy=call_policy(max_attempts=2),
        action_limits=ACTION_LIMITS,
        prompt_gateway=PromptGateway(None),
    )

    if exhausted:
        with pytest.raises(MaxRetriesExceeded) as caught:
            chooser.choose(req)
        calls = caught.value.calls
    else:
        calls = chooser.choose(req).calls

    assert len(calls) == len(provider.requests) == 2
    assert [call.payload["prompt_task"] for call in calls] == [
        "decide_action",
        "decide_action_retry",
    ]
    assert [call.payload["prompt_version"] for call in calls] == [
        active_version("decide_action"),
        active_version("decide_action_retry"),
    ]
    assert len(calls[0].payload["prompt_hash"]) == 64
    assert calls[0].error_kind == "ParseFailure"
    assert bool(calls[-1].error_kind) == exhausted


def _business_marker(raw: dict) -> str:
    """取业务视图里的一处数据原文，证明渲染确实消费了这份视图。"""
    for key in ("items", "bag", "party", "box"):
        rows = raw.get(key) or []
        if rows and rows[0].get("name"):
            return str(rows[0]["name"])
    for key in ("mine", "foe"):
        side = raw.get(key) or {}
        if side.get("name"):
            return str(side["name"])
    for key in ("target", "pokemon", "new_move"):
        if raw.get(key):
            return str(raw[key])
    return ""


@pytest.mark.parametrize(
    "path",
    sorted((GOLDEN / "decide_action").glob("synthetic-takeover-*.req.json")),
    ids=lambda path: path.stem,
)
def test_all_takeover_frames_render_their_business_view(path: Path) -> None:
    case = GoldenCase.model_validate_json(path.read_bytes())
    req = parse_request(case)
    req.obs.place = None

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert "- covered_by_script: true" in actual.text
    overlay = req.obs.facts.overlay.value if req.obs.facts.overlay else "none"
    assert f"- overlay: {overlay}" in actual.text
    assert "这一屏 10 列" not in actual.text
    if req.obs.takeover is not None:
        marker = _business_marker(case.request["obs"]["takeover"])
        assert marker and marker in actual.text
    elif req.obs.facts.screen:
        assert req.obs.facts.screen in actual.text
        assert "接管业务视图缺失" in actual.text
    else:
        assert "（未读出业务视图）" in actual.text


@pytest.mark.parametrize("scene", list(TaskScene))
@pytest.mark.parametrize("overlay", list(Facts.Overlay))
def test_frame_visibility_and_notes_keep_every_scene_overlay_branch(
    scene: TaskScene, overlay: Facts.Overlay
) -> None:
    req = native_request(overlay)
    req.obs.scene = scene
    req.obs.takeover = None
    req.obs.menu_decode_complete = False
    req.obs.facts.screen = "  TEXT  \n\n  > YES  "

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert f"- covered_by_script: {str(req.obs.covered_by_script).lower()}" in actual.text
    assert f"- overlay: {overlay.value}" in actual.text
    assert "- menu_decode_complete: false" in actual.text
    assert "选单切分不完整" in actual.text
    assert ("这一屏 10 列" in actual.text) is (not req.obs.covered_by_script)
    if req.obs.covered_by_script:
        assert "  TEXT\n  > YES" in actual.text
        assert "接管业务视图缺失" in actual.text
    elif scene in {TaskScene.WALK, TaskScene.SHOP} and overlay == Facts.Overlay.NONE:
        assert "- where: 全局坐标 地图1 x=2 y=3" in actual.text
    elif overlay == Facts.Overlay.DIALOG and scene not in {
        TaskScene.POKEMON_INFO,
        TaskScene.START_MENU,
        TaskScene.TITLE,
    }:
        assert "- dialog_text: 欢迎" in actual.text
    else:
        assert "- screen:   TEXT\n  > YES" in actual.text


@pytest.mark.parametrize("backend", ["local", "langfuse"])
def test_parse_timeout_success_preserves_input_and_attempt_specific_stamps(
    tmp_path: Path, backend: str
) -> None:
    from pokemon_agent.brain.errors import ToolTimeout

    req = native_request(Facts.Overlay.NONE)
    provider = ScriptedLLM(
        text_reply("x" * 450), ToolTimeout("offline timeout"), text_reply('{"action":"up"}')
    )
    gateway = PromptGateway(None)
    chooser = Chooser(
        Brain(decide_llm=provider),
        policy=call_policy(max_attempts=3),
        action_limits=ACTION_LIMITS,
        prompt_gateway=gateway,
    )
    base = gateway.render(
        "decide_action", decide_prompt_params(req, max_segments=ACTION_LIMITS.max_segments)
    )

    calls = chooser.choose(req).calls

    assert [call.payload["prompt_task"] for call in calls] == [
        "decide_action",
        "decide_action_retry",
        "decide_action",
    ]
    assert calls[0].payload["prompt_hash"] == calls[2].payload["prompt_hash"] == base.hash
    assert calls[1].payload["prompt_hash"] != base.hash
    prompts = [request.prompt for request in provider.requests]
    assert prompts[0] == prompts[2] == base.text
    assert prompts[1].startswith(base.text)
    assert "第 2 次尝试" in prompts[1]
    assert calls[0].error in prompts[1]
    raw = prompts[1].split("上次你输出的是：\n", 1)[1].split("\n\n", 1)[0]
    assert raw == "x" * 400
    assert calls[1].error_kind == "ToolTimeout"
    from _fake_langfuse import FakeLangfuseClient

    from pokemon_agent.direct.trace import TraceTool, parse
    from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
    from pokemon_agent.trace import LangfuseTrace

    if backend == "local":
        trace = TraceTool.build(run_id="run", trace_root=tmp_path / "trace")
    else:
        client = FakeLangfuseClient()
        trace = TraceTool(
            LangfuseTrace(trace_id=client.create_trace_id(seed="run"), client=client), run_id="run"
        )
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            calls=calls,
            meta={"source": "choose", "episode_id": "ep", "task_id": "task", "step": 1},
        )
    )
    model_events = [event for event in trace.read_events() if event.kind == TraceKind.CHOOSE_CALL]
    assert len(model_events) == len(calls)
    for call, event in zip(calls, model_events, strict=True):
        decoded = parse(event).content.model_dump()
        assert json.loads(event.content) == call.payload
        assert all(
            decoded[key] == call.payload[key]
            for key in ("prompt_task", "prompt_version", "prompt_hash")
        )


@pytest.mark.parametrize("default", [None, 0, 2, "", "a'b", "换行\n文本"])
def test_script_signature_defaults_keep_the_old_repr(default: str | int | None) -> None:
    from pokemon_agent.world import ActionEntry, ScriptParam

    req = native_request(Facts.Overlay.NONE, covered=True, script_only=True)
    req.space.entries = [
        ActionEntry(
            kind="script",
            name="example",
            description="说明",
            params=[
                ScriptParam(
                    name="value", type="int" if isinstance(default, int) else "str", default=default
                )
            ],
        )
    ]
    req.space.mask = {"example": True}

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    parameter = "int" if isinstance(default, int) else "str"
    signature = f"example(value: {parameter}"
    if default is not None:
        signature += f" = {default!r}"
    assert signature + ")：说明" in actual.text
