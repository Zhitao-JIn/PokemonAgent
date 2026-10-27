"""配置加载的用法：保底 `default.json` + 覆盖文件深度合并，非法配置在装配前被拒。"""

import json
from pathlib import Path

import pytest

from pokemon_agent.settings import (
    AppConfig,
    ConfigFileError,
    ConfigValidationError,
    SettingsError,
    load_config,
)


def write(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_default_alone_is_a_complete_valid_configuration() -> None:
    resolved = load_config()

    assert isinstance(resolved.config, AppConfig)
    assert len(resolved.sources) == 1 and resolved.sources[0].endswith("default.json")
    assert json.loads(resolved.merged_json)["budget"]["max_episodes"] == 10
    assert resolved.config.models.text.model == "qwen3.8-flash"
    assert resolved.config.review.mode == "off"


def test_overlay_changes_only_the_keys_it_names(tmp_path: Path) -> None:
    base = load_config().config
    overlay = write(tmp_path, "o.json", {"budget": {"max_episodes": 3}, "run": {"run_id": "x"}})

    config = load_config(overlay).config

    assert config.budget.max_episodes == 3 and config.run.run_id == "x"
    assert config.budget.task_max_steps == base.budget.task_max_steps
    assert config.models == base.models


def test_the_plan_freezing_switches_default_to_off() -> None:
    """两个冻结开关是评测专用覆盖项：保底配置里必须关着，缺一个都算配置不完整。"""
    loop = load_config().config.loop

    assert (loop.freeze_run_plan, loop.freeze_episode_plan) == (False, False)


def test_an_overlay_can_freeze_one_planning_layer(tmp_path: Path) -> None:
    """样本级覆盖只动它点名的那一层，另一层保持不冻结。"""
    overlay = write(tmp_path, "freeze.json", {"loop": {"freeze_run_plan": True}})

    loop = load_config(overlay).config.loop

    assert loop.freeze_run_plan and not loop.freeze_episode_plan


def test_later_overlays_win_and_lists_are_replaced_not_merged(tmp_path: Path) -> None:
    first = write(tmp_path, "a.json", {"review": {"layers": ["run", "episode", "task"]}})
    second = write(
        tmp_path, "b.json", {"review": {"layers": ["task"]}, "budget": {"max_episodes": 4}}
    )
    third = write(tmp_path, "c.json", {"budget": {"max_episodes": 5}})

    config = load_config([first, second, third]).config

    assert config.review.layers == ("task",)
    assert config.budget.max_episodes == 5


def test_the_digest_follows_the_effective_values_only(tmp_path: Path) -> None:
    same = write(tmp_path, "same.json", {"budget": {"max_episodes": 10}})
    other = write(tmp_path, "other.json", {"budget": {"max_episodes": 11}})

    assert load_config(same).sha256 == load_config().sha256
    assert load_config(other).sha256 != load_config().sha256


@pytest.mark.parametrize(
    "overlay",
    [
        {"unknown": 1},
        {"budget": {"unknown": 1}},
        {"budget": {"max_episodes": "3"}},
        {"budget": {"max_episodes": True}},
        {"budget": {"task_max_steps": 0}},
        {"budget": {"wall_clock_s": 60}},
        {"budget": {"task_max_steps": 20}},
        {"review": {"mode": "human", "link_url": None}},
        {"review": {"layers": ["run", "run"]}},
        {"models": {"plan": {"timeout_s": 1}}},
    ],
)
def test_invalid_configuration_is_rejected_before_assembly(tmp_path: Path, overlay: dict) -> None:
    path = write(tmp_path, "bad.json", overlay)

    with pytest.raises(ConfigValidationError) as caught:
        load_config(path)

    assert caught.value.issues and str(path) in caught.value.sources[-1]


def test_missing_unreadable_or_non_object_files_are_file_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    listing = write(tmp_path, "list.json", [1, 2])

    for path in (tmp_path / "missing.json", broken, listing):
        with pytest.raises(ConfigFileError):
            load_config(path)
    assert issubclass(ConfigFileError, SettingsError)


def test_secrets_have_no_place_in_the_schema(tmp_path: Path) -> None:
    path = write(tmp_path, "secret.json", {"models": {"text": {"api_key": "sk-x"}}})

    with pytest.raises(ConfigValidationError):
        load_config(path)
