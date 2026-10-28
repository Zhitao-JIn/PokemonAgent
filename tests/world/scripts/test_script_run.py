"""ScriptRun 骨架单测（FakeConsole）：三钩子、预算耗尽与逐键观察。

`FakeConsole` 不接真模拟器：帧序列 / map_id / 坐标都由测试脚本编排，钩子与缓存
行为因此可确定性复现。
"""

from __future__ import annotations

from typing import Any

from _doubles.world_console import FakeConsole

from pokemon_agent.world import ScreenText
from pokemon_agent.world.scripts.engine import ScriptRun
from pokemon_agent.world.scripts.interruptions import field_policy


def _run(frames: list[ScreenText], steps: list[str], *, budget: int = 5, map_id: int = 12) -> Any:
    console = FakeConsole(frames, map_id=map_id)
    return ScriptRun(
        console, budget=budget, start_map_id=12, start_pos=console.pos(), policy=field_policy()
    ).execute(steps)


def test_hook_battle_started() -> None:
    """场景变 BATTLE → 钩子抛 `battle_started`，ok=False。"""
    res = _run([ScreenText(), ScreenText(in_battle=True)], ["a"])
    assert res.code == "battle_started"
    assert res.ok is False
    assert "events" not in vars(res) and "dialog" not in vars(res)


def test_hook_choice_presented() -> None:
    """屏幕出现选项框 → `choice_presented`，选项文本进 data。"""
    frames = [ScreenText(), ScreenText(has_cursor=True, options=["YES", "NO"])]
    res = _run(frames, ["a"])
    assert res.code == "choice_presented"
    assert res.data["choice"] == "YES / NO"


def test_hook_map_changed_terminates() -> None:
    """换图 → `map_changed` 终止。"""
    res = _run([ScreenText(), ScreenText()], ["a"], map_id=13)
    assert res.code == "map_changed"
    assert "events" not in vars(res) and "dialog" not in vars(res)


def test_budget_exhausted() -> None:
    """预算先扣后按：预算 2、按 3 次 → 第 3 次按下前即 `budget_exhausted`。"""
    res = _run([ScreenText(), ScreenText(), ScreenText(), ScreenText()], ["a", "a", "a"], budget=2)
    assert res.code == "budget_exhausted"
    assert res.ok is False


def test_script_report_carries_observations_without_event_or_dialog_fields() -> None:
    """脚本逐键观察保留屏幕文字，终态对象不再带事件或单独对话字段。"""
    frames = [
        ScreenText(screen="x"),
        ScreenText(screen="x", dialog_text="A\nB"),
        ScreenText(screen="x", dialog_text="A\nB\nC"),
    ]
    console = FakeConsole(frames)
    run = ScriptRun(
        console, budget=5, start_map_id=12, start_pos=console.pos(), policy=field_policy()
    )
    res = run.execute(["a", "a"])
    assert res.ok is True
    assert [observation.dialog_text for observation in res.observations] == ["A\nB", "A\nB\nC"]
    assert "events" not in vars(res) and "dialog" not in vars(res)
