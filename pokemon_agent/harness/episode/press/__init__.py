"""域⑤ `press`：链内一圈的五个节点（**每键走一次**）。

`act` / `perceive_after_action` / `apply_stop` / `detect_stall` / `close_step`——图上
循环的正是这五个（含 `close_step` 出口那条分叉：队列还有键就回 `act`，空了才回链首
`open/save_checkpoint`）。

本域还对外交一个**图外的调用点**：`perceive_once`。开局那一帧由
`episode/episode_entry.py` 的 `begin_episode` 感知，它与图内 `perceive_after_action`
用的是同一个宿主（"谁消费这一帧，谁的账"）——两个调用点共用一份实现，是步 3 合并
`entry._perceive_first_frame` 与 `EpisodeHarness._perceive` 的结果。
"""

from __future__ import annotations

from .act import act
from .apply_stop import apply_stop
from .close_step import close_step
from .detect_stall import STALL_LIMIT, compute_stall, detect_stall
from .perceive_after_action import (
    PERCEPTION_MAX_RETRIES,
    compute_stop,
    perceive_after_action,
    perceive_once,
    perceive_with_retry,
)

__all__ = [
    "PERCEPTION_MAX_RETRIES",
    "STALL_LIMIT",
    "act",
    "apply_stop",
    "close_step",
    "compute_stall",
    "compute_stop",
    "detect_stall",
    "perceive_after_action",
    "perceive_once",
    "perceive_with_retry",
]
