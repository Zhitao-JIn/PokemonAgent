"""脚本评测的样本拼装：`frame()` 造一帧 task 档观测 + 内存读数，`run_of()` 拼 solver 产物。"""

from __future__ import annotations

from evals.world_script_execute.solver import ScriptReport, ScriptRun
from pokemon_agent.world import Facts, PlaceInWorld, RamReadout, TaskObservation, TaskScene
from pokemon_agent.world.interface import BagItem, DecodedText, MenuVars, PartyMon

POKE_BALL = 4


def frame(
    x: int = 9, y: int = 12, *, money: int = 3000, balls: int = 0, hp: int = 20
) -> tuple[TaskObservation, RamReadout]:
    """一帧 Route 1 上的 task 档观测 + 内存读数（只填判定要读的字段）。"""
    observation = TaskObservation(
        step=0,
        place=PlaceInWorld(map_id=12, x=x, y=y),
        status="",
        facts=Facts(facing="south"),
        scene=TaskScene.WALK,
    )
    ram = RamReadout(
        in_battle=False,
        covered=True,
        text_source="decode",
        menu=MenuVars(current_item=0, max_item=0, top_x=0),
        money=money,
        bag=[BagItem(item_id=POKE_BALL, quantity=balls)] if balls else [],
        party=[PartyMon(species=1, level=5, hp=hp, max_hp=20, status="ok")],
        decoded=DecodedText(dialog_text="", options=[], cursor=""),
    )
    return observation, ram


def run_of(
    report: ScriptReport | None,
    before: tuple[TaskObservation, RamReadout],
    after: tuple[TaskObservation, RamReadout],
    crash: str = "",
) -> ScriptRun:
    """拼一份 solver 产物。"""
    return ScriptRun(
        report=report,
        crash=crash,
        before_observation=before[0],
        before_ram=before[1],
        after_observation=after[0],
        after_ram=after[1],
        seconds=0.1,
    )
