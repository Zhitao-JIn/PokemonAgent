"""这个子系统自己的"内存读取"协议——只要能按地址取字节就行。

跟 `world_port.py` 放在同一层（不进 `domain/`）：`domain/` 是数据形状，这个是
行为契约（Protocol），两者的定位跟顶层 `interfaces/` 里"协议"和 `schemas/`
里"数据"的分工是同一套道理，只是这里的协议太小、太内部，不值得跑到顶层
`pokemon_agent/interfaces/` 去挂一个名字。

原来定义在 `world/ram.py`（"实现文档"）里——它是纯 `typing.Protocol`，没有任何
依赖，挪到这里零风险，可以放心立即加载。
"""

from __future__ import annotations

from typing import Protocol


class Memory(Protocol):
    """只要能按地址取字节就行。

    定义成 Protocol 而不是直接标 `PyBoy`：这个模块**不需要知道模拟器是谁**，
    也就不需要为了测它去起一个真模拟器。
    """

    def __getitem__(self, addr: int | slice) -> int | list[int]:
        """按地址或切片读原始字节。"""
        ...
