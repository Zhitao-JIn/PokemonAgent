"""流程类脚本单测（P4 第二批）：advance_dialog / wait_until_scene。

**对得上谁**：PLAN 附录 A #10（advance_dialog）与 #15（wait_until_scene）的单测列。
`DialogConsole` / `SceneConsole` 是脚本帧 / 场合序列的可编程替身。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.scripts.flow import advance_dialog, wait_until_scene

MAP = 12


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


class DialogConsole:
    """按键脚本帧：第 n 次按键后屏幕 = script[n-1]（与 TalkConsole 同语义）。

    advance_dialog 从"对话进行中"被调用，故 script[0] 就是第一句对话。
    """

    def __init__(self, script: list[dict[str, Any]], *, map_id: int = MAP) -> None:
        self._script = script
        self.presses = 0
        self._map_id = map_id
        self.x, self.y = 15, 8
        self._facing = "south"
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        self.presses += 1

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        if self.presses > 0 and self._script:
            over = self._script[min(self.presses - 1, len(self._script) - 1)]
        else:
            over = {}
        return ScreenText(
            in_battle=over.get("in_battle", False),
            dialog_text=over.get("dialog_text", ""),
            options=over.get("options", []),
            has_cursor=over.get("has_cursor", False),
        )

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def is_npc(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def scene(self) -> str:
        text = self.read()
        if text.in_battle:
            return "battle"
        if text.dialog_text:
            return "dialog"
        return "walk"


class SceneConsole:
    """场合序列：每 tick 推进一步；`scene()` 取当前阶段（wait_until_scene 用）。"""

    def __init__(self, scenes: list[str], *, map_id: int = MAP) -> None:
        self._scenes = scenes
        self._i = 0
        self._map_id = map_id
        self.x, self.y = 15, 8
        self._facing = "south"
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:  # noqa: ARG002
        pass

    def tick(self, frames: int) -> None:  # noqa: ARG002
        if self._i < len(self._scenes):
            self._i += 1

    def read(self) -> ScreenText:
        return ScreenText()

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def is_npc(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def scene(self) -> str:
        return self._scenes[min(self._i, len(self._scenes) - 1)]


# ---- advance_dialog（附录 A #10）----


def test_advance_dialog_three_frames_to_end() -> None:
    """① 三框对话推进到底：dialog 收全、回野外 → ok。"""
    console = DialogConsole(
        [{"dialog_text": "第一句"}, {"dialog_text": "第二句"}, {"dialog_text": "第三句"}, {}]
    )
    res = advance_dialog(console, max_presses=30)
    assert res.ok and res.code == "ok"
    assert res.data["dialog"] == ["第一句", "第二句", "第三句"]


def test_advance_dialog_still_talking_within_budget() -> None:
    """② 预算内推不完 → still_talking。"""
    script = [{"dialog_text": f"句{i}"} for i in range(40)] + [{}]
    console = DialogConsole(script)
    res = advance_dialog(console, max_presses=30)
    assert not res.ok and res.code == "still_talking"


def test_advance_dialog_choice_freezes() -> None:
    """对话里嵌选项 → choice_presented 冻结（绝不代选），已收文本照带。"""
    console = DialogConsole(
        [
            {"dialog_text": "要去冒险吗?"},
            {"options": ["YES", "NO"], "has_cursor": True, "dialog_text": "要去冒险吗?"},
        ]
    )
    res = advance_dialog(console, max_presses=30)
    assert not res.ok and res.code == "choice_presented"
    assert res.data["choice"] == "YES / NO"
    assert res.data["dialog"] == ["要去冒险吗?"]


# ---- wait_until_scene（附录 A #15）----


def test_wait_until_scene_success() -> None:
    """① 预设场合在 tick 中变化 → 成功。"""
    console = SceneConsole(["transition", "transition", "party", "party"])
    res = wait_until_scene(console, "party", timeout_s=5.0)
    assert res.ok and res.code == "ok"


def test_wait_until_scene_timeout() -> None:
    """② 场合始终不变 → timeout。"""
    console = SceneConsole(["walk", "walk", "walk"])
    res = wait_until_scene(console, "battle", timeout_s=0.3)
    assert not res.ok and res.code == "timeout"
    assert res.data["scene"] == "walk"
