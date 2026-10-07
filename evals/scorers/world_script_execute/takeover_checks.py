"""接管用例的评分核对。"""

from __future__ import annotations

from collections.abc import Callable

from evals.scorers.world_script_execute.verdict import ScriptVerdict
from evals.solvers.world_script_execute import ScriptRun
from pokemon_agent.world import TaskObservation, TaskScene
from pokemon_agent.world.scripts.execution_types import ScriptStatus


def _money(delta: int) -> Check:
    """金钱变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _shop(after).money - _shop(before).money
        return "" if got == delta else f"金钱变化 {got}，期望 {delta}"

    return check


def _bag(item: str, delta: int) -> Check:
    """背包里 `item` 的数量变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _count(after, item) - _count(before, item)
        return "" if got == delta else f"{item} 变化 {got}，期望 {delta}"

    return check


def _scene(scene: TaskScene) -> Check:
    """收尾后的场合。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        return "" if after.scene is scene else f"收尾场合 {after.scene.value}，期望 {scene.value}"

    return check


def _left(scene: TaskScene) -> Check:
    """收尾后已离开 `scene`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        return "" if after.scene is not scene else f"收尾仍在 {scene.value}"

    return check


def _battle_start(before: TaskObservation, after: TaskObservation) -> str:
    """收尾停在战斗行动菜单（FIGHT / PKMN / ITEM / RUN）。"""
    ok = after.scene is TaskScene.BATTLE_MENU and after.facts.cursor in (
        "FIGHT",
        "PKMN",
        "ITEM",
        "RUN",
    )
    return "" if ok else f"收尾不在行动菜单（{after.scene.value}，光标 {after.facts.cursor!r}）"


def _in_play(name: str) -> Check:
    """收尾时在场的是 `name`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        view = after.takeover
        mine = view.mine.name if view is not None and view.kind == "battle_menu" else ""
        return "" if mine == name else f"在场的是 {mine!r}，期望 {name}"

    return check


def _foe_hurt(before: TaskObservation, after: TaskObservation) -> str:
    """对手 HP 少了。"""
    hp0, hp1 = _foe_hp(before), _foe_hp(after)
    return "" if hp1 < hp0 else f"对手 HP {hp0}→{hp1}，没有少"


def _foe_hp(obs: TaskObservation) -> int:
    assert obs.takeover is not None and obs.takeover.kind == "battle_menu", "不在战斗选单"
    return obs.takeover.foe.hp


def _shop_start(before: TaskObservation, after: TaskObservation) -> str:
    """收尾停在商店主菜单（BUY / SELL / QUIT，实心光标，没有上一层的空心光标）。"""
    screen = after.facts.screen
    ok = "BUY" in screen and "▶" in screen and "▷" not in screen
    return "" if ok else "收尾不在商店主菜单"


def _shop(obs: TaskObservation):  # noqa: ANN202
    assert obs.takeover is not None and obs.takeover.kind == "shop_items", "不在商店"
    return obs.takeover


def _count(obs: TaskObservation, item: str) -> int:
    view = obs.takeover
    assert view is not None and hasattr(view, "bag"), "视图里没有背包"
    return sum(b.quantity for b in view.bag if b.name == item)


def _pc(item: str, delta: int) -> Check:
    """PC 里 `item` 的数量变化恰为 `delta`。"""

    def count(obs: TaskObservation) -> int:
        assert obs.takeover is not None and obs.takeover.kind == "pc", "不在 PC"
        return sum(b.quantity for b in obs.takeover.items if b.name == item)

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = count(after) - count(before)
        return "" if got == delta else f"PC 里 {item} 变化 {got}，期望 {delta}"

    return check


def _party_names(obs: TaskObservation) -> list[str]:
    view = obs.takeover
    assert view is not None and hasattr(view, "party"), "视图里没有队伍"
    return [m.name for m in view.party]


def _order(*names: str) -> Check:
    """收尾时队伍顺序。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _party_names(after)
        return "" if got == list(names) else f"队伍顺序 {got}，期望 {list(names)}"

    return check


def _box(delta: int) -> Check:
    """当前箱只数变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = len(after.takeover.box) - len(before.takeover.box)  # type: ignore[union-attr]
        return "" if got == delta else f"箱里只数变化 {got}，期望 {delta}"

    return check


def _knows(pokemon: str, move: str, *, yes: bool = True) -> Check:
    """收尾时 `pokemon` 会（或不会）`move`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        view = after.takeover
        assert view is not None and hasattr(view, "party"), "视图里没有队伍"
        mon = next((m for m in view.party if m.name == pokemon), None)
        knows = mon is not None and move in [x.name for x in mon.moves]
        return "" if knows == yes else f"{pokemon} {'不会' if yes else '会'} {move}"

    return check


def judge_takeover(case_id: str, run: ScriptRun) -> ScriptVerdict:
    """报告按原结局契约判，状态变化只读前后观测，不信脚本自述。"""
    from evals.solvers.world_script_cases.takeover_cases import CASES

    case = next(c for c in CASES if c.case_id == case_id)
    problems: list[str] = []
    report = run.report
    code = "ok" if case.status is ScriptStatus.DONE else (case.reason or case.status).value
    if report is None:
        problems.append(run.crash)
    else:
        if report.code != code or report.data.get("status") != case.status.value:
            problems.append(f"结局不符：{report.code}/{report.data.get('status')}")
        if report.ok != (case.status is ScriptStatus.DONE):
            problems.append(f"ok={report.ok}")
        if case.summary and case.summary not in str(report.data.get("summary", "")):
            problems.append(f"摘要缺少 {case.summary!r}")
    truth: list[str] = []
    for check in case.checks:
        try:
            problem = check(run.before_observation, run.after_observation)
        except AssertionError as exc:
            problem = str(exc)
        if problem:
            truth.append(problem)
    return ScriptVerdict(code_problems=problems, truth_problems=truth)


Check = Callable[[TaskObservation, TaskObservation], str]
