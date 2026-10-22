"""图片上限纯函数与装配期预算契约，不调用模型或模拟器。"""

from pathlib import Path

import pytest

from pokemon_agent.direct.brain_tool import cap_images
from pokemon_agent.settings import ConfigValidationError, load_config


@pytest.mark.parametrize(
    "frames, cap, expected",
    [
        (["a", "b"], 3, ["a", "b"]),
        (["a", "b"], 2, ["a", "b"]),
        (["a", "b", "c"], 2, ["b", "c"]),
        ([], 2, []),
    ],
)
def test_cap_images_keeps_newest_and_drops_oldest(
    frames: list[str], cap: int, expected: list[str]
) -> None:
    original = list(frames)

    result = cap_images(frames, cap)

    assert result == expected
    assert result is not frames
    assert frames == original


@pytest.mark.parametrize("cap", [0, -1])
def test_cap_images_rejects_nonpositive_caps(cap: int) -> None:
    with pytest.raises(AssertionError, match="positive cap"):
        cap_images(["frame"], cap)


def test_config_rejects_image_cap_below_task_steps_plus_one(tmp_path: Path) -> None:
    overlay = tmp_path / "budget.json"
    overlay.write_text('{"budget":{"task_max_steps":20}}', encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=r"scope_image_cap.*task_max_steps \+ 1"):
        load_config(overlay)
