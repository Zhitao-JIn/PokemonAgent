"""离线起点生成器所需的字节写入契约。"""

from typing import Protocol

from pokemon_agent.world.interface import Memory


class WritableMemory(Memory, Protocol):
    """支持读取与单字节修改；调用方保证地址和数值在模拟器范围内。"""

    def __setitem__(self, address: int, value: int) -> None:
        """将 0..255 的值写入合法地址；模拟器写入失败直接上抛。"""
        ...
