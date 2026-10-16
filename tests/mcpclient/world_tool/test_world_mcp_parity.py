"""MCP 门面的事件、静态文案与前置契约同进程内路径一致。"""

from __future__ import annotations

from typing import Any

import pytest

from pokemon_agent.brain.interface import Action, ActionSegment, Goal, ScriptCall
from pokemon_agent.direct.prompts.decide_action import build_prompt
from pokemon_agent.mcpclient.action_space import action_space_for
from pokemon_agent.mcpclient.game_tools import GameTools
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
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
        step=0,
        status="你在野外。",
        scene=scene,
        place=PlaceInWorld(map_id=12, x=13, y=8),
        facts=Facts(overlay=overlay),
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
def test_get_action_space_adds_prompt_text_like_the_in_process_path(
    tool: WorldMcpTool,
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
    scene: TaskScene,
    overlay: Facts.Overlay,
) -> None:
    """同一观测经两条路径所得空间与完整 prompt 逐字节相等。"""
    observation = _observation(scene, overlay)
    monkeypatch.setattr(world, "_observation", lambda: observation)
    request = FromHarnessToGameToolGetActionSpaceReq(observation=observation)

    remote = tool.get_action_space(request).action_space
    local = GameTools(world).get_action_space(request).action_space

    assert remote.model_dump() == local.model_dump()
    assert remote.model_dump() == action_space_for(observation, list(ALL_BUTTONS)).model_dump()
    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="走到目标", criteria="到达目标格")],
        obs=observation,
        space=local,
        memories=[],
    )
    local_prompt = build_prompt(request)
    remote_prompt = build_prompt(request.model_copy(update={"space": remote}))
    assert remote_prompt == local_prompt
    assert remote_prompt.encode("utf-8") == local_prompt.encode("utf-8")


@pytest.mark.parametrize("scene", [TaskScene.WALK, TaskScene.PARTY])
@pytest.mark.parametrize("overlay", list(Facts.Overlay))
def test_prompt_text_is_deterministic_and_frame_independent(
    scene: TaskScene,
    overlay: Facts.Overlay,
) -> None:
    """改变坐标、步数与屏幕内容，不改变同场合叠加层下的三份静态文案。"""
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

    assert first.descriptions == second.descriptions
    assert first.note == second.note
    assert first.map_note == second.map_note


@pytest.mark.parametrize("names", [["select"], ["up", "down"]])
def test_execute_rejects_a_key_outside_the_mask(
    tool: WorldMcpTool,
    world: Any,
    client: Any,
    names: list[str],
) -> None:
    """非法键或未展开的多键在任何 MCP 调用前失败，错误文本同 GameTools。"""
    request = FromHarnessToGameToolExecuteReq(
        action=Action(sequence=[ActionSegment(name=name, times=1) for name in names]),
        observation=_observation(TaskScene.WALK, Facts.Overlay.NONE),
    )

    with pytest.raises(AssertionError) as local:
        GameTools(world).execute(request)
    with pytest.raises(AssertionError) as remote:
        tool.execute(request)

    assert str(remote.value) == str(local.value)
    assert client.calls == []


@pytest.mark.parametrize("name", ["shop_quit", "invented_script"])
def test_execute_rejects_a_script_outside_the_space(
    tool: WorldMcpTool,
    world: Any,
    client: Any,
    name: str,
) -> None:
    """其他场合的脚本与不存在的脚本都在本地拒绝，错误文本同 GameTools。"""
    request = FromHarnessToGameToolExecuteReq(
        action=Action(script=ScriptCall(name=name, args={})),
        observation=_observation(TaskScene.WALK, Facts.Overlay.NONE),
    )

    with pytest.raises(AssertionError) as local:
        GameTools(world).execute(request)
    with pytest.raises(AssertionError) as remote:
        tool.execute(request)

    assert str(remote.value) == str(local.value)
    assert client.calls == []
