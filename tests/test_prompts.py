"""prompt 加载与渲染的测试。

守的是三件事：占位符漏传要炸、sha 跟着内容变、prompt 里的字段清单和代码不漂移。
"""

from __future__ import annotations

import re

import pytest

from pokemon_agent.prompts import PromptTemplate, load
from pokemon_agent.schemas.screen import (
    SCENE_FIELDS,
    Overlay,
    Scene,
    ScreenState,
    describe_scene_fields,
)


def rendered() -> str:
    """感知 prompt 没有占位符——内容全部写死在文件里，打开就能看到发出去的原文。"""
    return load("perceive_screen").render()


def test_missing_placeholder_raises_instead_of_leaking_literal():
    """漏传变量当场炸，不能把字面量 `$foo` 发给模型。

    用 substitute 而不是 safe_substitute 就是为了这个：
    悄悄发出去会得到一个看似正常的错误结果，那种 bug 最难查。
    """
    with pytest.raises(KeyError):
        load("decide_action").render(goal="x")  # 少了 summary/facts/... 等


def test_perceive_prompt_has_no_placeholders_left():
    """感知 prompt 必须是完整的、可直接阅读的原文。

    当初把 prompt 挪进 .md 的理由就是"可 review"。
    如果打开文件看到的是 `$scene_fields`，那个理由就不成立了。
    """
    text = load("perceive_screen").text

    assert "$" not in text, "感知 prompt 里不该有占位符，内容要写死"


def test_sha_tracks_content_not_a_hand_written_version():
    """sha 是内容哈希。改内容忘改版本号是必然事件，而归因一旦错，整批实验数据作废。"""
    a = PromptTemplate(name="t", text="hello", sha="")
    same = load("perceive_screen")

    assert same.sha == load("perceive_screen").sha, "同一内容必须得到同一 sha"
    assert len(same.sha) == 12
    assert a.sha != same.sha


def test_every_scene_appears_in_the_prompt():
    """prompt 里的字段清单由 SCENE_FIELDS 生成，不手写。

    手写必然漂移：给某个 scene 加了字段却忘了改 prompt，
    模型不填、代码等着，两边都不报错。
    """
    text = rendered()

    for scene, fields in SCENE_FIELDS.items():
        assert f"`{scene.value}`" in text, f"prompt 里缺 scene {scene.value}"
        for f in fields:
            assert f"`{f}`" in text, f"prompt 里缺字段 {f}"


def test_every_overlay_appears_in_the_prompt():
    for overlay in Overlay:
        assert f"`{overlay.value}`" in overlay.value or overlay.value in rendered()


def test_the_example_written_in_the_prompt_actually_parses():
    """**从 .md 里抠出那段 JSON，验证它真的能变成 ScreenState。**

    样例是手写的（为了文件可读），所以必须有人验证它合法：
    错的样例比没有样例更糟，模型会照着它学。
    这条测试就是"手写"的代价，也是它的保险。
    """
    text = load("perceive_screen").text
    block = re.search(r"```json\n(.*?)\n```", text, re.S)

    assert block, "prompt 里应当有一段 ```json 输出样例"
    parsed = ScreenState.model_validate_json(block.group(1))

    assert parsed.scene is Scene.BATTLE
    assert parsed.overlay is Overlay.CHOICE
    assert parsed.available_actions() == ("up", "down", "a", "b")
    assert set(parsed.fields) <= set(parsed.expected_fields()), "样例里出现了该 scene 没有的字段"


def test_scene_field_list_in_the_prompt_matches_the_code():
    """手写的字段清单和 SCENE_FIELDS 对照，漂移当场失败。

    这就是"内容写死在文件里"的安全网：可读性靠手写，防漂移靠这条测试，
    两个目标用两种手段，不必互相牺牲。
    """
    text = load("perceive_screen").text

    for line in describe_scene_fields().splitlines():
        assert line in text, f"prompt 与 SCENE_FIELDS 漂移了，缺这行：\n  {line}"


def test_battle_layout_rule_is_stated_explicitly():
    """实测两个模型都把敌我搞反了，所以布局必须写成硬规则。

    这条测试是为了防止以后有人"精简" prompt 时把它删掉。
    """
    text = rendered()

    assert "左上角" in text and "对手" in text
    assert "右下角" in text and "我方" in text
    assert "PP" in text, "35/35 是 PP 不是 HP，这条实测被两个模型都搞错过"


def test_unknown_prompt_lists_what_is_available():
    with pytest.raises(FileNotFoundError, match="perceive_screen"):
        load("no_such_prompt")
