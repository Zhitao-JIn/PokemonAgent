"""脚本拥有的执行策略：稳定等待、中断、准备、恢复与收尾。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .execution_types import ScriptStatus
from .timing import POLL_FRAMES, STABLE_POLLS, STEP_TIMEOUT_FRAMES

if TYPE_CHECKING:
    from .engine import ScriptRun

Hook = Callable[["ScriptRun"], None]
Reset = Callable[["ScriptRun"], ScriptStatus | None]


@dataclass(frozen=True)
class StableWait:
    """一次稳定等待的参数；超时是否中止由调用脚本决定。"""

    poll_frames: int = POLL_FRAMES
    stable_polls: int = STABLE_POLLS
    timeout_frames: int = STEP_TIMEOUT_FRAMES
    abort_on_timeout: bool = False

    def __post_init__(self) -> None:
        """前置条件：三个等待预算均为正数。"""
        assert min(self.poll_frames, self.stable_polls, self.timeout_frames) > 0


@dataclass(frozen=True)
class ScriptPolicy:
    """统一执行器只执行声明的规则；没有配置的中断或收尾不自行启用。"""

    wait: StableWait = field(default_factory=StableWait)
    interruptions: tuple[Hook, ...] = ()
    before: Hook | None = None
    after: Hook | None = None
    on_error: Hook | None = None
    reset: Reset | None = None
    record_steps: bool = False
