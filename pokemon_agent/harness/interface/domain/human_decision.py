"""人类对"下一层怎么办"的决策枚举。

原来放在 `schemas/harness/domain/`；跟着"协议物理挨着它自己的实现"这条
原则搬到了 `harness/interface/domain/`。
"""

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
