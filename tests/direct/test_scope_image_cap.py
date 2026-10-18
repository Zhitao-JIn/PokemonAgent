"""图片上限纯函数与装配期预算契约，不调用模型或模拟器。"""

from pathlib import Path

import pytest

from pokemon_agent.direct.brain_tool import cap_images


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


def test_assembly_rejects_image_cap_below_task_steps_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pokemon_agent.build as assembly

    config = tmp_path / "budget.json"
    config.write_text('{"budget":{"task_max_steps":20}}', encoding="utf-8")

    def after_budget() -> None:
        pytest.fail("assembly continued past the image-cap assertion")

    monkeypatch.setattr(assembly, "load_env_file", after_budget)

    with pytest.raises(AssertionError, match=r"SCOPE_IMAGE_CAP=20.*task_max_steps \+ 1=21"):
        assembly.build_real(config=config)
