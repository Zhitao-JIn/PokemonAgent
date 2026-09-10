"""人类对“下一层怎么办”的决策枚举。"""

from __future__ import annotations

from enum import Enum


class HumanDecision(str, Enum):
    """人类对"下一层怎么办"的决策。"""

    CONTINUE = "continue"
    """继续下一层（默认）。"""
    STOP = "stop"
    """停止整个 run。"""
    RETRY = "retry"
    """重试刚跑完的那一层（把上一层的目标重新压回栈顶）。"""
