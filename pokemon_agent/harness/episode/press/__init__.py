"""域⑤ `press`：链内一圈的五个节点（**每键走一次**）。

`act` / `perceive_after_action` / `detect_stall` / `close_step`——图上
循环的正是这五个（含 `close_step` 出口那条分叉：队列还有键就回 `act`，空了才回链首
`open/save_checkpoint`）。

本域还对外交一个**图外的调用点**：`perceive_once`。开局那一帧由
`episode/episode_entry.py` 的 `begin_episode` 感知，它与图内 `perceive_after_action`
用的是同一个宿主（"谁消费这一帧，谁的账"）——两个调用点共用一份实现，是步 3 合并
`entry._perceive_first_frame` 与 `EpisodeHarness._perceive` 的结果。

**重试循环不在这里**（0913 夜）：`perceive_with_retry` 已搬去
`GameTools.perceive_with_retry()`（对齐 `BrainTool._attempt_loop`），
本域只再导出 `perceive_once` 这一个宿主。
"""

from __future__ import annotations

from .act import act
from .close_step import close_step
from .detect_stall import compute_stall, detect_stall
from .perceive_after_action import (
    perceive_after_action,
    perceive_once,
)

__all__ = [
    "act",
    "close_step",
    "compute_stall",
    "detect_stall",
    "perceive_after_action",
    "perceive_once",
]
