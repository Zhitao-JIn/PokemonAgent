"""perceive 测评的用法示范：拿数据集里的一帧（截图 + WRAM 快照）跑生产感知节点，再逐字段判。

视觉模型用替身（不连网、不起模拟器）；快照内存要 ROM 的 bank 0，没有 ROM 的环境整篇跳过。
"""

from __future__ import annotations

import pytest
from _doubles.vision import DownVision
from _doubles.world_console import FakeConsole, FakeMemory

from evals.common.world_case import ROM
from evals.dataset.frames.loader import load_samples
from evals.dataset.frames.schemas import ScreenSample
from evals.dataset.frames.snapshot import has_map, snapshot_of
from evals.episode_vision_read.compare import field_verdict, truth_fields
from evals.episode_vision_read.dataset import output_for
from evals.episode_vision_read.solver import ProviderUnreachable, perceive_sample
from pokemon_agent.world import Facts, VisionDescribeResp
from pokemon_agent.world.interface import ScreenState
from pokemon_agent.world.ram import OVERWORLD_TILESET, W_CUR_MAP_TILESET

pytestmark = pytest.mark.skipif(not ROM.is_file(), reason="需要 ROM（assets/rom，不进 git）")


def judge_fields(frame, run):
    """从新纯比较接口读取各适用字段的 C/I/N。"""
    return {
        key: field_verdict(output_for(run), truth_fields(frame), key)
        for key in ("scene", "overlay", "dialog_text", "options", "cursor", "parsed")
    }


class FixedVision:
    """每次都答同一段文字的视觉替身。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def describe(self, req: object) -> VisionDescribeResp:
        """原样答。"""
        return VisionDescribeResp(text=self.text, input_tokens=10, output_tokens=5)


@pytest.fixture(scope="module")
def dialog_frame() -> ScreenSample:
    """一帧野外 / 室内的对话（标注 overlay=dialog）。"""
    return next(
        s
        for s in load_samples("v2")
        if has_map(s) and s.label.scene == "dialog" and s.label.dialog_text
    )


def answer(frame: ScreenSample, scene: Facts.Scene) -> str:
    """照标注写一份视觉回答。"""
    label = frame.label
    return ScreenState(
        scene=scene, overlay=label.overlay, overview="一句概况", dialog_text=label.dialog_text
    ).model_dump_json()


def test_a_frame_read_exactly_as_labelled_is_correct_on_every_judgeable_field(
    dialog_frame: ScreenSample,
) -> None:
    _, memory = snapshot_of(dialog_frame)
    outdoor = memory[W_CUR_MAP_TILESET] == OVERWORLD_TILESET
    scene = Facts.Scene.FIELD if outdoor else Facts.Scene.INDOOR

    run = perceive_sample(dialog_frame, FixedVision(answer(dialog_frame, scene)))
    verdict = judge_fields(dialog_frame, run)

    assert {k: v.value for k, v in verdict.items()} == {
        "scene": "C",
        "overlay": "C",
        "dialog_text": "C",
        "options": "N",
        "cursor": "N",
        "parsed": "C",
    }


def test_an_unparseable_answer_fails_only_the_fields_this_frame_can_judge(
    dialog_frame: ScreenSample,
) -> None:
    run = perceive_sample(dialog_frame, FixedVision("我看到一个对话框"))

    verdict = judge_fields(dialog_frame, run)

    assert run.facts is None and run.raw == "我看到一个对话框"
    assert verdict["parsed"].value == "I"
    assert verdict["dialog_text"].value == "I"
    assert verdict["options"].value == "N"


def test_an_unreachable_model_is_an_infrastructure_error_not_a_misread(
    dialog_frame: ScreenSample,
) -> None:
    with pytest.raises(ProviderUnreachable, match="gateway down"):
        perceive_sample(dialog_frame, DownVision())


@pytest.mark.parametrize(
    ("sample_id", "scene", "cursor"),
    [
        ("c-0039", "naming", "Q"),
        ("c-0866", "battle_switch", "BB?!"),
        ("c-0946", "party", "PP!?"),
        ("p-option_screen", "start_menu", "MEDIUM"),
        ("p-battle_use_on_which", "battle_menu", "BULBASAUR"),
        ("c-0002", "transition", ""),
        ("c-0015", "transition", ""),
        ("c-0241", "battle_menu", ""),
        ("c-0252", "battle_menu", ""),
    ],
)
def test_frozen_layouts_identify_the_scene_and_selected_target(
    sample_id: str, scene: str, cursor: str
) -> None:
    from evals.decode.solver import decode_frame

    frame = next(sample for sample in load_samples("v2") if sample.sample_id == sample_id)

    result = decode_frame(frame)

    assert result.scene["scene"] == scene
    assert result.screen["cursor"] == cursor
    if cursor:
        row, column = result.screen["cursor_cell"]
        assert result.screen["option_grid"][row][column] == cursor


@pytest.mark.parametrize("sample_id", ["c-0242", "p-battle_menu_pkmn", "p-battle_menu_item"])
def test_battle_menu_away_from_fight_is_not_the_normalized_start(sample_id: str) -> None:
    from evals.decode.solver import decode_frame

    frame = next(sample for sample in load_samples("v2") if sample.sample_id == sample_id)

    result = decode_frame(frame)

    assert result.scene["scene"] == "battle_menu"
    assert result.scene["at_start"] is False


@pytest.mark.parametrize(
    "sample_id",
    [
        "c-0272",
        "c-0088",
        "c-0355",
        "c-0257",
        "c-0273",
        "c-0198",
        "c-0239",
        "c-0493",
        "c-0589",
        "c-0467",
        "c-0225",
        "c-0766",
        "c-0003",
        "c-0010",
        "c-0247",
        "c-0659",
        "c-0440",
        "c-0419",
        "c-0243",
        "c-0954",
        "c-0037",
        "p-stats_page",
        "c-0420",
        "c-0434",
        "c-0952",
        "c-0578",
        "c-0582",
        "c-0492",
        "c-0497",
    ],
)
def test_audited_frames_match_all_four_approved_field_groups(sample_id: str) -> None:
    """各项修复的代表帧与易误伤的背景菜单共用冻结输入和批准真值。"""
    from evals.dataset.frames import load
    from evals.decode.compare import field_verdict
    from evals.decode.solver import decode_frame

    frame = next(frame for frame in load() if frame.sample_id == sample_id)

    result = decode_frame(frame)

    for group in ("scene", "screen", "takeover", "terrain"):
        truth = getattr(frame, f"{group}_truth")
        for key in truth or {}:
            verdict = field_verdict(getattr(result, group), truth, key)
            assert verdict.value == "C", f"{group}.{key}: {verdict.reason}"
        if not truth:
            assert getattr(result, group) == {}


def test_unsettled_map_does_not_publish_mixed_coordinates_in_either_perception_path() -> None:
    from pokemon_agent.world.perceive_frame import perceive_frame
    from pokemon_agent.world.prompts import load
    from pokemon_agent.world.screen_text import read_screen_text
    from pokemon_agent.world.task_perception import observe_task

    frame = next(frame for frame in load_samples("v2") if frame.sample_id == "c-0273")
    png, memory = snapshot_of(frame)
    vision = FixedVision(
        ScreenState(scene="transition", overlay="none", overview="换图").model_dump_json()
    )

    episode = perceive_frame(png, memory, template=load("perceive_screen"), vision=vision)
    task = observe_task(
        None, read_screen_text(memory), png, memory=memory, rom=ROM.read_bytes(), closed=False
    )

    for observation in (episode.observation, task.observation):
        assert observation.place is None
        assert observation.facts.map_id is None
        assert (
            observation.facts.where
            == observation.facts.walk_map
            == observation.facts.neighbors
            == ""
        )
        assert observation.facts.landmarks == []


@pytest.mark.parametrize(
    ("naming_type", "length", "accepted"),
    [(0, 7, True), (1, 8, False), (2, 10, True), (2, 11, False)],
)
def test_naming_script_checks_lengths_from_the_game_type(
    naming_type: int, length: int, accepted: bool
) -> None:
    from pokemon_agent.world import ScreenText
    from pokemon_agent.world.interface import PlaceInWorld
    from pokemon_agent.world.scripts.engine import ScriptRun
    from pokemon_agent.world.scripts.scenes.naming import NAMING_SCRIPTS, W_NAMING_SCREEN_TYPE

    console = FakeConsole([ScreenText(screen="BULBASAUR")])
    console.memory = FakeMemory(**{str(W_NAMING_SCREEN_TYPE): naming_type})
    definition = NAMING_SCRIPTS["enter_name"]
    run = ScriptRun(
        console,
        budget=1,
        start_map_id=12,
        start_pos=PlaceInWorld(map_id=12, x=1, y=1),
        policy=definition.policy,
    )

    error = definition.check(run, {"name": "A" * length})

    assert (error is None) is accepted
