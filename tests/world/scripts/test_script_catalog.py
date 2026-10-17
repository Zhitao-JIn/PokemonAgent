"""脚本目录与场合可用性：`script_entries` 按场合给脚本条目；`run_script_by_name` 按名字分发。"""

from __future__ import annotations

from _doubles.world_console import StubConsole

from pokemon_agent.world.scripts.catalog import SCRIPT_SPECS, run_script_by_name, script_entries
from pokemon_agent.world.scripts.scenes import SCRIPT_DEFINITIONS

FIELD_SCRIPTS = set(SCRIPT_SPECS) - set(SCRIPT_DEFINITIONS) - {"buy_item", "sell_item"}


# ---- 1. 目录与场合可用性 ----


def test_catalog_has_fourteen_regular_scripts_plus_takeover_scripts() -> None:
    assert len(SCRIPT_SPECS) == 14 + len(SCRIPT_DEFINITIONS)


def test_walk_scene_gets_every_field_script() -> None:
    assert {e.name for e in script_entries("walk")} == FIELD_SCRIPTS


def test_shop_scene_gets_checked_buy_sell_and_quit() -> None:
    assert {e.name for e in script_entries("shop_items")} == {"buy_item", "sell_item", "shop_quit"}


def test_dialog_scene_gets_only_dialog_scripts() -> None:
    assert {e.name for e in script_entries("dialog")} == {
        "advance_dialog",
        "wait_until_scene",
    }


def test_battle_scene_gets_no_scripts() -> None:
    assert script_entries("battle") == []


# ---- 7. run_script_by_name 分发 ----


def test_run_script_by_name_dispatches_and_reports() -> None:

    console = StubConsole()
    result = run_script_by_name(console, "face_direction", {"direction": "north"})
    assert result.ok and console.facing() == "north"
