"""`act` 格（task 层）：**只按键**——把 `plan_task` 选的那一个键交给世界，键数 +1。

按键之后的一切（感知新帧、停摆、ActMemory、object 事件、扶正）都在下一圈的
`perceive` 里；本格出口无条件回 `perceive`。
"""

from __future__ import annotations

from .act import act

__all__ = ["act"]
