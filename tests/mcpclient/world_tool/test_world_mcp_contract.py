"""MCP 门面的事件、静态文案与执行前置契约。"""

from __future__ import annotations

from typing import Any

import pytest
from _harness_fixtures.app_config import ACTION_LIMITS

from pokemon_agent.brain.interface import Action, ActionSegment, Goal, ScriptCall
from pokemon_agent.direct.brain_tool import decide_prompt_params
from pokemon_agent.mcpclient.action_space import action_space_for
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
)
from pokemon_agent.world import Facts, PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.action_space import ALL_BUTTONS


def _observation(scene: TaskScene, overlay: Facts.Overlay) -> TaskObservation:
    """同一位置的假观测，由测试选择场合与叠加层。"""
    return TaskObservation(
        step=0, scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8), facts=Facts(overlay=overlay)
    )


def _after_press_frame(observation: TaskObservation, pressed: bool) -> TaskObservation:
    """假世界按键前无对话、按键后出现固定对话，仍由真判定器决定是否产生事件。"""
    return observation.model_copy(
        update={
            "facts": observation.facts.model_copy(
                update={"dialog_text": "你好。" if pressed else ""}
            )
        }
    )


@pytest.mark.parametrize("mode", ["dialog", "null", "missing"])
def test_execute_returns_the_event_the_server_judged(
    tool: WorldMcpTool, world: Any, client: Any, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """真 observe_step 判定对话或无事件，MCP 信封中的事件原样进入 Port。"""
    observation = _observation(TaskScene.WALK, Facts.Overlay.NONE)
    observation.facts = Facts(
        facing="south",
        landmarks=[Facts.Landmark(kind="人", map_id=12, x=13, y=9)] if mode == "dialog" else [],
    )
    monkeypatch.setattr(
        world, "_observation", lambda: _after_press_frame(observation, bool(world.calls))
    )
    original = client.call_tool_sync

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        body = original(name, arguments)
        if mode == "missing":
            body["data"].pop("event")
        return body

    monkeypatch.setattr(client, "call_tool_sync", call)

    response = tool.execute(
        FromHarnessToGameToolExecuteReq(
            action=Action(sequence=[ActionSegment(name="a", times=1)]),
            observation=observation,
        )
    )

    expected = (
        {
            "outcome": "dialog",
            "actor_place": observation.place.model_dump(),
            "place": {"map_id": 12, "x": 13, "y": 9},
            "object_kind": "人",
            "button": "a",
            "text": "你好。",
        }
        if mode == "dialog"
        else None
    )
    assert response.event == expected
    assert client.calls[0][0] == "step" and len(client.calls) == 1


@pytest.mark.parametrize(
    "scene,overlay",
    [
        (TaskScene.WALK, Facts.Overlay.NONE),
        (TaskScene.WALK, Facts.Overlay.CHOICE),
        (TaskScene.PARTY, Facts.Overlay.NONE),
        (TaskScene.BAG, Facts.Overlay.DIALOG),
    ],
)
def test_get_action_space_matches_the_local_raw_contract_and_gateway(
    tool: WorldMcpTool,
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
    scene: TaskScene,
    overlay: Facts.Overlay,
) -> None:
    """MCP 返回的空间与共用纯函数基准相等，完整 prompt 逐字节相等。"""
    observation = _observation(scene, overlay)
    monkeypatch.setattr(world, "_observation", lambda: observation)
    request = FromHarnessToGameToolGetActionSpaceReq(observation=observation)

    remote = tool.get_action_space(request).action_space
    local = action_space_for(observation, list(ALL_BUTTONS))

    assert remote.model_dump() == local.model_dump()
    assert remote.model_dump() == action_space_for(observation, list(ALL_BUTTONS)).model_dump()
    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="走到目标", criteria="到达目标格")],
        obs=observation,
        space=local,
        memories=[],
    )
    gateway = PromptGateway(None)
    local_prompt = gateway.render(
        "decide_action", decide_prompt_params(request, max_segments=ACTION_LIMITS.max_segments)
    ).text
    remote_prompt = gateway.render(
        "decide_action",
        decide_prompt_params(
            request.model_copy(update={"space": remote}), max_segments=ACTION_LIMITS.max_segments
        ),
    ).text
    assert remote_prompt == local_prompt
    assert remote_prompt.encode("utf-8") == local_prompt.encode("utf-8")


@pytest.mark.parametrize("scene", [TaskScene.WALK, TaskScene.PARTY])
@pytest.mark.parametrize("overlay", list(Facts.Overlay))
def test_action_space_never_contains_prompt_text_in_any_frame(
    scene: TaskScene,
    overlay: Facts.Overlay,
) -> None:
    """改变坐标、步数与屏幕内容，动作协议均只包含原始能力字段。"""
    before = _observation(scene, overlay)
    after = before.model_copy(
        update={
            "step": 99,
            "status": "不同帧",
            "place": PlaceInWorld(map_id=3, x=4, y=5),
            "facts": Facts(overlay=overlay, screen="不同屏幕", dialog_text="变化的对话"),
        }
    )

    first = action_space_for(before, list(ALL_BUTTONS))
    second = action_space_for(after, list(ALL_BUTTONS))

    assert set(first.model_dump()) == {"scene", "mask", "entries", "names"}
    assert set(second.model_dump()) == {"scene", "mask", "entries", "names"}


@pytest.mark.parametrize("names", [["select"], ["up", "down"]])
def test_execute_rejects_a_key_outside_the_mask(
    tool: WorldMcpTool,
    client: Any,
    names: list[str],
) -> None:
    """非法键或未展开的多键在任何 MCP 调用前失败，错误文本符合原契约。"""
    request = FromHarnessToGameToolExecuteReq(
        action=Action(sequence=[ActionSegment(name=name, times=1) for name in names]),
        observation=_observation(TaskScene.WALK, Facts.Overlay.NONE),
    )

    with pytest.raises(AssertionError) as remote:
        tool.execute(request)

    space = action_space_for(request.observation, list(ALL_BUTTONS))
    expected = (
        f"execute() got {names[0]!r} outside {space.names}"
        if len(names) == 1
        else "execute() 只接受单键动作；连按应由 Harness 的循环展开成多步"
    )
    assert str(remote.value) == expected
    assert client.calls == []


@pytest.mark.parametrize("name", ["shop_quit", "invented_script"])
def test_execute_rejects_a_script_outside_the_space(
    tool: WorldMcpTool,
    client: Any,
    name: str,
) -> None:
    """其他场合的脚本与不存在的脚本都在本地拒绝，错误文本符合原契约。"""
    request = FromHarnessToGameToolExecuteReq(
        action=Action(script=ScriptCall(name=name, args={})),
        observation=_observation(TaskScene.WALK, Facts.Overlay.NONE),
    )

    with pytest.raises(AssertionError) as remote:
        tool.execute(request)

    space = action_space_for(request.observation, list(ALL_BUTTONS))
    script_names = [entry.name for entry in space.entries if entry.kind == "script"]
    assert str(remote.value) == f"execute() got script {name!r} outside {script_names}"
    assert client.calls == []


def test_structured_observation_fields_cross_the_real_mcp_serialization(
    tool: WorldMcpTool, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = _observation(TaskScene.WALK, Facts.Overlay.NONE)
    observation.facts = Facts(
        neighbor_cells={"up": "G"},
        cells=["##########"] * 9,
        option_grid=[["YES", "NO"]],
        cursor_cell=(0, 1),
        option_annotations=["", "×2"],
        terrain_visible=True,
    )
    monkeypatch.setattr(world, "_observation", lambda: observation)

    response = tool.perceive_task()

    assert response.observation.facts.model_dump() == observation.facts.model_dump()
    assert response.observation.observation_flags == observation.observation_flags
