"""brain 包：纯决策层。无状态——每一步的全部输入来自参数，全部记忆来自工具调用。

只依赖 `interfaces/` 与 `schemas/`，不 import 任何具体实现（铁律 2）。

本文件是统一出口：消费方只写 `from pokemon_agent.brain import Brain`。
"""

__all__ = [
    "Brain",
]
from .brain import Brain
