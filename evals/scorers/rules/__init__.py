"""全部机械判据：导入即登记进 `evals.scorers.registry.RULES`。只做导入。"""

from __future__ import annotations

from . import battle, catch, center, dialog, movement, shop

__all__ = ["battle", "catch", "center", "dialog", "movement", "shop"]
