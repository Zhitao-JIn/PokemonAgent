"""统一的画面稳定等待，策略决定预算与超时语义。"""

from .control_flow import Abort
from .execution_types import ScriptReason
from .interface import WorldConsole
from .policies import StableWait


def settle_screen(console: WorldConsole, settings: StableWait) -> int:
    """返回等待帧数；连续画面稳定才成功，超时按脚本策略返回或抛 Abort。"""
    waited, same, last = 0, 0, None
    while waited < settings.timeout_frames:
        console.tick(settings.poll_frames)
        waited += settings.poll_frames
        now = console.read().screen.replace("▼", " ")
        same = same + 1 if now == last else 0
        last = now
        if same >= settings.stable_polls:
            return waited
    if settings.abort_on_timeout:
        raise Abort(ScriptReason.STEP_TIMEOUT, f"画面 {settings.timeout_frames} 帧内没有稳定下来")
    return waited
