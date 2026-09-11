"""harness/interface/domain 包：`HumanDecision`——人类对"下一层怎么办"的决策枚举。

原来放在 `schemas/harness/domain/`，跟着"协议物理挨着它自己的实现/数据形状"
这条原则搬到了这里。零依赖，可以放心立即加载。
"""

from __future__ import annotations

from .human_decision import HumanDecision

__all__ = [
    "HumanDecision",
]
