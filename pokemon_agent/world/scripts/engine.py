"""统一脚本现场：按键后记录紧凑观察，等待与步骤记录遵循策略。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..interface import Memory, PlaceInWorld, ScreenText, TaskScene
from ..interface.domain.step_observation import FacingObject, RamState, StepObservation
from ..readout import read_readout
from ..scene import classify_scene
from ..screen_text import overlay_of
from . import screen_steps
from .control_flow import Abort, Halt, ScriptResult
from .execution_types import ScriptStatus, ScriptStep
from .interface import WorldConsole
from .policies import ScriptPolicy
from .screen_wait import settle_screen
from .tables import POKECENTER_LAYOUTS, SHOP_LAYOUTS, WARPS


class ScriptRun:
    """一次调用的现场；未声明的中断、初态恢复与收尾不会自动执行。"""

    def __init__(
        self,
        console: WorldConsole,
        *,
        budget: int,
        start_map_id: int,
        start_pos: PlaceInWorld,
        policy: ScriptPolicy | None = None,
        scene: TaskScene | None = None,
    ) -> None:
        self.console = console
        self.budget = budget
        self.start_map_id = start_map_id
        self.start_pos = start_pos
        self.policy = policy if policy is not None else ScriptPolicy()
        self.scene = scene if scene is not None else self.scene_now()
        self.steps: list[ScriptStep] = []
        self.observations: list[StepObservation] = []
        self.calls: list[Any] = []

    @property
    def mem(self) -> Memory:
        """当前内存；读取不推进世界。"""
        return self.console.memory

    def screen(self) -> ScreenText:
        """返回当前画面；读取不推进世界。"""
        return self.console.read()

    def scene_now(self) -> TaskScene:
        """根据当前画面与内存分类场合。"""
        return classify_scene(self.screen(), self.mem)

    def settle(self) -> int:
        """按脚本等待策略推进；严格超时抛 Abort，其余返回等待帧数。"""
        return settle_screen(self.console, self.policy.wait)

    def _press(self, key: str, *, settle: bool) -> tuple[ScreenText, int, bool]:
        """统一按键路径：推进、等待、记录观察并执行声明的中断。"""
        before = self.console.pos()
        self.console.press(key)
        try:
            frames = self.settle() if settle else 0
        except Abort:
            self._observe(self.screen(), settled=False)
            raise
        text = self.screen()
        self._observe(text, settled=frames < self.policy.wait.timeout_frames)
        after = self.console.pos()
        for interrupt in self.policy.interruptions:
            interrupt(self)
        return text, frames, after != before

    def _observe(self, text: ScreenText, *, settled: bool) -> None:
        """追加本键的只读快照；调用方已完成等待，读取不会推进帧或执行按键。"""
        readout = read_readout(self.mem, text, text_source="decode")
        place, facing = self.console.pos(), self.console.facing()
        target = place.step_toward(facing) if facing else None
        kind = self.console.object_kind(target.x, target.y) if target is not None else None
        self.observations.append(
            StepObservation(
                step=len(self.observations) + 1,
                place=place,
                facing=facing,
                scene=classify_scene(text, self.mem),
                overlay=overlay_of(text),
                dialog_text=text.dialog_text,
                options=text.options,
                cursor=text.cursor,
                screen=text.screen,
                ram=RamState.model_validate(readout.model_dump()),
                facing_object=FacingObject(kind=kind, place=target) if kind and target else None,
                battle_status=readout.battle if readout.in_battle else None,
                settled=settled,
            )
        )

    def press(self, key: str, *, settle: bool = True) -> bool:
        """按一键，返回是否位移；声明的中断以 Halt 报告。"""
        return self._press(key, settle=settle)[2]

    def press_screen(
        self, key: str, *, expect: str = "", ok: Callable[[ScreenText], bool] | None = None
    ) -> ScreenText:
        """同一路径按键并返回画面；核对结果由脚本决定如何处理。"""
        text, frames, _ = self._press(key, settle=True)
        self.record_step(
            ScriptStep(
                key=key,
                frames=frames,
                expect=expect,
                actual=screen_steps.brief(text),
                ok=ok(text) if ok else True,
            )
        )
        return text

    def record_step(self, step: ScriptStep) -> None:
        """只在本脚本声明记录明细时追加步骤。"""
        if self.policy.record_steps:
            self.steps.append(step)

    def wait_for(
        self,
        ok: Callable[[ScreenText], bool],
        *,
        expect: str,
        advance: Callable[[ScreenText], bool] | None = None,
    ) -> ScreenText:
        """等待画面，只在调用方允许时按 A；失败抛 Abort。"""
        return screen_steps.wait_for(self, ok, expect=expect, advance=advance)

    def idle_until(self, ok: Callable[[ScreenText], bool], *, expect: str) -> ScreenText:
        """只推进帧等待画面；预算内未出现时抛 Abort。"""
        return screen_steps.idle_until(self, ok, expect=expect)

    def advance(self, stop: Callable[[ScreenText], str]) -> str:
        """安全推进文字到指定条件，返回停止说明。"""
        return screen_steps.advance(self, stop)

    def _saw_arrow(self) -> bool:
        """观察一个闪烁窗口内是否出现推进箭头。"""
        return screen_steps.saw_arrow(self)

    def move_to(
        self, read: Callable[[], int], target: int, *, what: str, increase: str = "down"
    ) -> None:
        """把读数导航到目标；步数内达不到时抛 Abort。"""
        screen_steps.move_to(self, read, target, what=what, increase=increase)

    def rewind(self) -> ScriptStatus | None:
        """执行声明的恢复步骤；未声明时不按键。"""
        return self.policy.reset(self) if self.policy.reset else None

    def _snapshot(self) -> dict[str, Any]:
        text = self.screen()
        return {
            "pos": self.console.pos().model_dump(),
            "scene": classify_scene(text, self.mem).value,
            "screen_text": text.screen,
        }

    def execute(self, steps: Iterable[str], *, settle: bool = True) -> ScriptResult:
        """按预算执行按键序列；第 N+1 键在按下前报告预算耗尽。"""
        try:
            for key in steps:
                if self.budget <= 0:
                    raise Halt("budget_exhausted")
                self.budget -= 1
                self.press(key, settle=settle)
        except Halt as halt:
            return self.finish(ok=halt.ok, code=halt.code, extra=halt.extra)
        return self.finish(ok=True, code="ok")

    def finish(self, *, ok: bool, code: str, extra: dict[str, Any] | None = None) -> ScriptResult:
        """把终态与业务载荷合成统一报告；不隐式执行恢复。"""
        data = self._snapshot()
        if extra:
            data.update(extra)
        return ScriptResult(
            ok=ok,
            code=code,
            data=data,
            calls=self.calls,
            observations=list(self.observations),
        )


def run_script(
    console: WorldConsole,
    steps: Iterable[str],
    *,
    budget: int,
    start_map_id: int,
    start_pos: PlaceInWorld,
    settle: bool = True,
    policy: ScriptPolicy | None = None,
) -> ScriptResult:
    """执行按键序列；等待与中断遵循传入策略。"""
    return ScriptRun(
        console, budget=budget, start_map_id=start_map_id, start_pos=start_pos, policy=policy
    ).execute(steps, settle=settle)


__all__ = [
    "Abort",
    "Halt",
    "WARPS",
    "SHOP_LAYOUTS",
    "POKECENTER_LAYOUTS",
    "ScriptResult",
    "ScriptRun",
    "WorldConsole",
    "run_script",
]
