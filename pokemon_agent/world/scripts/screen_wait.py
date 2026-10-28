"""统一的画面稳定等待，策略决定预算与超时语义。"""

from dataclasses import dataclass

from ..interface import TaskScene
from ..scene import classify_scene
from .control_flow import Abort
from .execution_types import ScriptReason
from .interface import WorldConsole
from .policies import StableWait
from .timing import BATTLE_STABLE_POLLS, BATTLE_TIMEOUT_FRAMES


@dataclass(frozen=True)
class WaitResult:
    """等待帧数与是否达到稳定阈值。"""

    waited_frames: int
    settled: bool


_BATTLE_SCENES = frozenset({TaskScene.BATTLE, TaskScene.BATTLE_MENU, TaskScene.BATTLE_SWITCH})


def wait_settled(
    console: WorldConsole,
    settings: StableWait | None = None,
    *,
    before_scene: TaskScene | str | None = None,
) -> WaitResult:
    """推进至文字与玩家位置连续稳定；等待期间出现战斗场景后粘性升级预算。

    前置条件：console 可读取屏幕、内存与位置并推进帧。
    超时返回 settled=False；策略要求时抛 Abort。
    """
    selected = settings or StableWait()
    stable_polls = selected.stable_polls
    timeout_frames = selected.timeout_frames
    battle_seen = before_scene is not None and TaskScene(before_scene) in _BATTLE_SCENES
    waited_frames = 0
    same_polls = 0
    first_text = console.read()
    first_scene = classify_scene(first_text, console.memory)
    if first_scene in _BATTLE_SCENES:
        battle_seen = True
    if battle_seen:
        stable_polls = max(stable_polls, BATTLE_STABLE_POLLS)
        timeout_frames = max(timeout_frames, BATTLE_TIMEOUT_FRAMES)
    previous: tuple[str, object] = (
        first_text.screen.replace("▼", " "),
        console.pos(),
    )
    settled = False
    while waited_frames < timeout_frames:
        poll_frames = min(selected.poll_frames, timeout_frames - waited_frames)
        console.tick(poll_frames)
        waited_frames += poll_frames
        text = console.read()
        scene = classify_scene(text, console.memory)
        if scene in _BATTLE_SCENES:
            battle_seen = True
        if battle_seen:
            stable_polls = max(stable_polls, BATTLE_STABLE_POLLS)
            timeout_frames = max(timeout_frames, BATTLE_TIMEOUT_FRAMES)
        current = (text.screen.replace("▼", " "), console.pos())
        same_polls = same_polls + 1 if current == previous else 0
        previous = current
        if same_polls >= stable_polls:
            settled = True
            break
    if not settled and selected.abort_on_timeout:
        raise Abort(ScriptReason.STEP_TIMEOUT, f"画面 {timeout_frames} 帧内没有稳定下来")
    return WaitResult(waited_frames=waited_frames, settled=settled)
