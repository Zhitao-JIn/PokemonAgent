"""同一个脚本执行器由策略控制等待、中断、准备与收尾。"""

import pytest
from test_script_run import FakeConsole

from pokemon_agent.world import ActionEntry, PlaceInWorld, ScreenText, TaskScene
from pokemon_agent.world.scripts.catalog import script_entries
from pokemon_agent.world.scripts.control_flow import Abort
from pokemon_agent.world.scripts.definitions import ScriptDefinition, run_definition
from pokemon_agent.world.scripts.engine import ScriptRun
from pokemon_agent.world.scripts.execution_types import ScriptReason
from pokemon_agent.world.scripts.interruptions import field_policy
from pokemon_agent.world.scripts.policies import ScriptPolicy, StableWait
from pokemon_agent.world.scripts.scenes.policy import menu_policy, reset_menu


@pytest.mark.parametrize(
    ("route", "keys"),
    [
        ([(1, 1), (0, 1), (0, 0)], ["up", "left"]),
        ([(0, 1), (0, 0)], ["left"]),
        ([(1, 0), (0, 0)], ["up"]),
        ([(0, 0)], []),
    ],
)
def test_battle_menu_reset_moves_to_fight_without_selecting_an_action(
    route: list[tuple[int, int]], keys: list[str]
) -> None:
    grid = [["FIGHT", "PKMN"], ["ITEM", "RUN"]]
    frames = [
        ScreenText(
            screen="FIGHT PKMN ITEM RUN",
            in_battle=True,
            has_cursor=True,
            options=["FIGHT", "PKMN", "ITEM", "RUN"],
            option_grid=grid,
            cursor_cell=cell,
            cursor=grid[cell[0]][cell[1]],
        )
        for cell in route
    ]
    console = FakeConsole(frames)
    run = ScriptRun(
        console,
        budget=10,
        start_map_id=12,
        start_pos=console.pos(),
        scene=TaskScene.BATTLE_MENU,
        policy=menu_policy(),
    )

    status = reset_menu(run)

    assert status is None
    assert run.screen().cursor == "FIGHT"
    assert [step.key for step in run.steps] == keys


def test_interruptions_are_opt_in_for_the_same_runtime() -> None:
    frames = [ScreenText(), ScreenText(in_battle=True)]
    allowed = FakeConsole(frames)
    stopped = FakeConsole(frames)

    result = ScriptRun(
        allowed, budget=1, start_map_id=12, start_pos=allowed.pos(), policy=ScriptPolicy()
    ).execute(["a"])
    interrupted = ScriptRun(
        stopped, budget=1, start_map_id=12, start_pos=stopped.pos(), policy=field_policy()
    ).execute(["a"])

    assert result.ok
    assert interrupted.code == "battle_started"


def test_definition_owns_preparation_and_finalization() -> None:
    phases: list[str] = []

    def prepare(run: ScriptRun) -> None:
        phases.append("prepare")

    def execute(run: ScriptRun, args: dict[str, str | int]) -> str:
        phases.append("execute")
        run.press_screen("a")
        return "finished"

    def finalize(run: ScriptRun) -> None:
        phases.append("finalize")

    definition = ScriptDefinition(
        spec=ActionEntry(kind="script", name="example", description="example"),
        scene=TaskScene.WALK,
        check=lambda run, args: None,
        execute=execute,
        policy=ScriptPolicy(before=prepare, after=finalize),
    )
    console = FakeConsole([ScreenText(), ScreenText()])

    result = run_definition(console, definition, {})

    assert result.ok and result.data["summary"] == "finished"
    assert phases == ["prepare", "execute", "finalize"]


def test_waiting_is_configured_for_a_step() -> None:
    console = FakeConsole([ScreenText()])
    ticks: list[int] = []
    console.tick = ticks.append
    run = ScriptRun(
        console,
        budget=1,
        start_map_id=12,
        start_pos=console.pos(),
        policy=ScriptPolicy(wait=StableWait(poll_frames=2, stable_polls=2)),
    )

    run.press("a")

    assert ticks == [2, 2, 2]


def test_blank_screen_does_not_end_wait_before_animation_lands() -> None:
    console = FakeConsole([ScreenText()])
    elapsed = 0

    def tick(frames: int) -> None:
        nonlocal elapsed
        elapsed += frames
        console._pos = PlaceInWorld(map_id=12, x=9, y=13 if elapsed < 40 else 14)

    console.tick = tick
    run = ScriptRun(
        console,
        budget=1,
        start_map_id=12,
        start_pos=console.pos(),
        policy=ScriptPolicy(wait=StableWait(minimum_frames=64)),
    )

    run.press("down")

    assert elapsed >= 64
    assert console.pos().y == 14


@pytest.mark.parametrize("rejected", [False, True])
def test_recovery_runs_only_after_execution_failure(rejected: bool) -> None:
    phases: list[str] = []

    def check(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
        return (ScriptReason.CANNOT_USE, "rejected") if rejected else None

    def execute(run: ScriptRun, args: dict[str, str | int]) -> str:
        phases.append("execute")
        raise Abort(ScriptReason.UNEXPECTED_SCREEN, "failed")

    definition = ScriptDefinition(
        spec=ActionEntry(kind="script", name="example", description="example"),
        scene=TaskScene.WALK,
        check=check,
        execute=execute,
        policy=ScriptPolicy(
            before=lambda run: phases.append("prepare"),
            after=lambda run: phases.append("finalize"),
            on_error=lambda run: phases.append("recover"),
        ),
    )

    result = run_definition(FakeConsole([ScreenText()]), definition, {})

    assert not result.ok
    assert result.data["status"] == ("rejected" if rejected else "aborted")
    assert phases == (["prepare"] if rejected else ["prepare", "execute", "recover"])


def test_a_definition_accepts_its_declared_alternate_entry_scene() -> None:
    console = FakeConsole([ScreenText(screen="Choose a POK", in_battle=True)])
    definition = ScriptDefinition(
        spec=ActionEntry(kind="script", name="example", description="example"),
        scene=TaskScene.BATTLE_MENU,
        entry_scenes=(TaskScene.BATTLE_SWITCH,),
        check=lambda run, args: None,
        execute=lambda run, args: "selected",
    )

    result = run_definition(console, definition, {})

    assert result.ok
    assert result.data["scene"] == "battle_switch"


def test_switch_is_available_from_both_battle_menus_but_fight_is_not() -> None:
    menu = {entry.name for entry in script_entries("battle_menu")}
    party = {entry.name for entry in script_entries("battle_switch")}

    assert "battle_switch" in menu & party
    assert "switch_send_out" in party
    assert "battle_fight" not in party
