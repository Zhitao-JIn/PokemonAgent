"""实时输入仅带结构化字段；添加旧投影不会改变任何模型输入字节。"""

import copy

import pytest

from pokemon_agent.direct.brain_tool import decide_prompt_params
from pokemon_agent.prompt import DecomposeParams, JudgeParams, PromptGateway, VerifyParams
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolDecomposeReq,
)
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import (
    TERRAIN_MEANING,
    Facts,
    PlaceInWorld,
    ScreenText,
    TaskObservation,
    TaskScene,
)
from pokemon_agent.world.screen_text import overlay_of


def observation() -> TaskObservation:
    return TaskObservation(
        step=0,
        scene=TaskScene.WALK,
        place=PlaceInWorld(map_id=12, x=3, y=4),
        facts=Facts(
            overlay=Facts.Overlay.CHOICE,
            map_id=12,
            neighbor_cells={"up": "#", "down": ".", "left": "G", "right": "N"},
            cells=["##########"] * 9,
            terrain_visible=True,
            options=["YES", "NO"],
            option_grid=[["YES"], ["NO"]],
            cursor_cell=(1, 0),
            option_annotations=["×2", ""],
            battle_status=None,
        ),
    )


@pytest.mark.parametrize("task", ["decompose", "judge_success", "decide_action", "verify"])
def test_structured_live_input_and_added_legacy_projections_are_byte_equal(task: str) -> None:
    obs = observation()
    raw = obs.model_dump(mode="json")
    legacy = copy.deepcopy(raw)
    legacy["status"] = "old status must be ignored"
    legacy["observation_notes"] = ["old notes must be ignored"]
    legacy["facts"].update(
        where="stale",
        neighbors="stale",
        walk_map="stale",
        option_layout="stale",
        option_details="stale",
        my_hp="stale",
        foe_hp="stale",
    )
    gateway = PromptGateway(None)

    def render(value: dict) -> bytes:
        if task == "decompose":
            params = DecomposeParams.model_validate(
                {
                    "goal": {"goal": "g", "criteria": "c"},
                    "observation": value,
                    "max_tasks": 1,
                    "terrain_meanings": TERRAIN_MEANING,
                }
            )
        elif task == "judge_success":
            params = JudgeParams.model_validate(
                {"goal": {"goal": "g", "criteria": "c"}, "observation": value}
            )
        elif task == "decide_action":
            req = FromHarnessToBrainToolChooseOnceReq.model_validate(
                {
                    "goals": [{"goal": "g", "criteria": "c"}],
                    "obs": raw,
                    "space": {"names": ["a"]},
                    "memories": [],
                }
            )
            base = decide_prompt_params(req, max_segments=3)
            params = type(base).model_validate(
                {**base.model_dump(mode="json"), "observation": value}
            )
        else:
            params = VerifyParams.model_validate(
                {
                    "goal": "g",
                    "entries": [
                        {
                            "before": value,
                            "after": value,
                            "action": "a",
                            "step": 0,
                            "episode_id": "e",
                        }
                    ],
                }
            )
        return gateway.render(task, params).text.encode("utf-8")

    assert render(raw) == render(legacy)


def test_real_decomposition_entry_accepts_observation_without_status() -> None:
    req = FromHarnessToBrainToolDecomposeReq.model_validate(
        {
            "goal": {"goal": "g", "criteria": "c"},
            "observation": observation().model_dump(mode="json"),
            "max_tasks": 1,
        }
    )

    params = DecomposeParams.model_validate(
        {**req.model_dump(mode="json"), "terrain_meanings": TERRAIN_MEANING}
    )

    assert "status" not in req.observation.model_dump()
    assert params.observation.status == ""
    assert "全局坐标 地图12 x=3 y=4" in PromptGateway(None).render("decompose", params).text


def test_live_overlay_prevents_empty_facts_status_fallback() -> None:
    assert overlay_of(ScreenText()) is Facts.Overlay.NONE
    assert "status" not in TaskObservation.model_fields
    assert "status" not in ActMemory.Observation.model_fields
    assert not {"where", "neighbors", "walk_map"} & Facts.model_fields.keys()
    assert not {"where", "neighbors", "walk_map"} & ActMemory.Observation.Facts.model_fields.keys()
