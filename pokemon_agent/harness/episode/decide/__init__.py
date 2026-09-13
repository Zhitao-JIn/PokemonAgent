"""域④ `decide`：一次决策一格。

`think_action` 是本域唯一的节点——它把"这一步做什么"定型，产出的链交给 `press/`
逐键执行。图上它前面是四路检索的汇聚点 `merge_retrieval`，后面是链内小循环的入口 `act`。

**重试循环不在这里**：搬到 `BrainTool.choose()` 那一层（a+c 方案）——
拼重试纠正说明是"拥有这次调用"的那层的事，本域只负责组装、交一次、落账。
"""

from __future__ import annotations

from .think_action import think_action

__all__ = [
    "think_action",
]
