"""域② `gate`：判停与空间——**出循环与进循环的两个闸口**。

`judge` 判"这一局该不该停"（图上唯一的终止判定），`get_action_space` 算"这一步
能按什么"。两者都不改 `observation`、不碰记忆：一个只看已有证据下结论，一个只把
世界的合法动作边界抄成一条账。
"""

from __future__ import annotations

from .get_action_space import get_action_space
from .judge import judge

__all__ = [
    "get_action_space",
    "judge",
]
