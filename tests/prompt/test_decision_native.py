"""无文案的原生动作空间经版本模板保持旧模型输入。"""

import json
from pathlib import Path

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import ACTION_LIMITS, call_policy

from pokemon_agent.brain import Brain, Goal
from pokemon_agent.direct.brain_tool import Chooser, decide_prompt_params
from pokemon_agent.direct.prompts import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.direct.prompts.decide_action import build_prompt
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.mcpclient.action_space import action_space_for
from pokemon_agent.prompt import DecideActionRetryParams, PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world import ActionSpace, Facts, PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import NamingView
from scripts.capture_prompt_golden import GoldenCase

GOLDEN = Path(__file__).parent / "golden"


def native_request(
    overlay: Facts.Overlay, covered: bool = False, script_only: bool = False
) -> FromHarnessToBrainToolChooseOnceReq:
    place = PlaceInWorld(map_id=1, x=2, y=3)
    observation = TaskObservation(
        step=0,
        status="旧状态行",
        place=place,
        scene=TaskScene.NAMING
        if covered
        else TaskScene.DIALOG
        if overlay == Facts.Overlay.DIALOG
        else TaskScene.WALK,
        takeover=NamingView(target="YOUR NAME?", typed="R") if covered else None,
        facts=Facts(
            overlay=overlay,
            where=place.render(),
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
def test_native_action_space_without_display_fields_keeps_the_old_prompt(
    overlay: Facts.Overlay, covered: bool
) -> None:
    req = native_request(overlay, covered)
    legacy_space = req.space.model_copy(
        update={
            "descriptions": {
                name: BUTTON_HELP[overlay].get(name, BUTTON_HELP[Facts.Overlay.NONE].get(name, ""))
                for name in req.space.names
            },
            "note": REPEAT_HINT,
            "map_note": "" if covered else MAP_HINT,
        }
    )
    expected = build_prompt(req.model_copy(update={"space": legacy_space}), max_segments=3)

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert {"descriptions", "note", "map_note"}.isdisjoint(req.space.model_dump())
    assert actual.text.encode("utf-8") == expected.encode("utf-8")


def test_a_script_only_action_space_keeps_its_old_prompt() -> None:
    req = native_request(Facts.Overlay.NONE, covered=True, script_only=True)

    actual = PromptGateway(None).render("decide_action", decide_prompt_params(req, max_segments=3))

    assert actual.text == build_prompt(req, max_segments=3)
    assert req.space.names == []


def test_frozen_action_space_display_keys_roundtrip_as_legacy_extensions() -> None:
    path = sorted((GOLDEN / "decide_action").glob("history-*.req.json"))[0]
    raw = json.loads(path.read_bytes())["request"]["space"]

    space = ActionSpace.model_validate(raw)

    assert space.model_dump(mode="json") == raw
    assert {"descriptions", "note", "map_note"}.isdisjoint(ActionSpace.model_fields)
    assert {"descriptions", "note", "map_note"} <= space.model_extra.keys()


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
    assert all(call.payload["prompt_task"] == "decide_action" for call in calls)
    assert all(call.payload["prompt_version"] == "v1" for call in calls)
    assert len(calls[0].payload["prompt_hash"]) == 64
    assert calls[0].error_kind == "ParseFailure"
    assert bool(calls[-1].error_kind) == exhausted
