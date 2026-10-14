"""ScriptRun 骨架单测（FakeConsole）：三钩子各一条、预算耗尽一条、对话增量三例。

**对得上谁**：与 P2 `world_server.step` 的钩子判定一致——battle / choice / map_changed
终止 + 对话增量缓存。脚本逻辑（P4）在骨架上叠主循环，本文件只验骨架本身。

`FakeConsole` 不接真模拟器：帧序列 / map_id / 坐标都由测试脚本编排，钩子与缓存
行为因此可确定性复现。
"""

from __future__ import annotations

from typing import Any

from _doubles.world_console import FakeConsole

from pokemon_agent.world import ScreenText
from pokemon_agent.world.scripts.engine import DialogCache, ScriptRun
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
    assert res.events == []  # battle 是终止钩子，不进 events[]


def test_hook_choice_presented() -> None:
    """屏幕出现选项框 → `choice_presented`，选项文本进 data。"""
    frames = [ScreenText(), ScreenText(has_cursor=True, options=["YES", "NO"])]
    res = _run(frames, ["a"])
    assert res.code == "choice_presented"
    assert res.data["choice"] == "YES / NO"


def test_hook_map_changed_terminates_without_object_event() -> None:
    """换图 → `map_changed` 终止。脚下/邻格没有"门"物件时，warp 事件不产
    （P6 起事件判定在 `judge_press`，普通边缘出口不是交互物）。"""
    res = _run([ScreenText(), ScreenText()], ["a"], map_id=13)
    assert res.code == "map_changed"
    assert res.events == []


def test_budget_exhausted() -> None:
    """预算先扣后按：预算 2、按 3 次 → 第 3 次按下前即 `budget_exhausted`。"""
    res = _run([ScreenText(), ScreenText(), ScreenText(), ScreenText()], ["a", "a", "a"], budget=2)
    assert res.code == "budget_exhausted"
    assert res.ok is False


def test_dialog_cache_three_examples() -> None:
    """对话增量三例（§3.5）：首框全量 / 滚动增量 / 全已见无事件。"""
    cache = DialogCache()
    assert cache.ingest("A\nB\nC") == "A\nB\nC"  # 首框全量
    assert cache.ingest("A\nB\nC\nD") == "D"  # 滚动增量（只新增末行）
    assert cache.ingest("A\nB\nC") == ""  # 全已见 → 无事件
    cache.reset()
    assert cache.ingest("A\nB\nC") == "A\nB\nC"  # 清空后重新全量


def test_dialog_deltas_collected_across_steps() -> None:
    """ScriptRun 层面：逐键推进，对话增量按帧累积进 `dialog.deltas`，不重复。

    P6 起脚本的对话载荷与事件分流：增量在 `dialog.deltas`（脚本结果载荷用），
    `events[]` 由 `judge_press` 统一判（无交互物 → 空列表）。
    """
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
    assert run.dialog.deltas == ["A\nB", "C"]
    assert res.events == []
