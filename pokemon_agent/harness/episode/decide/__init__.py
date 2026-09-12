"""域④ `decide`：一次决策一格。

`think_action` 自带重试循环（问模型失败要重试），是本域唯一的节点——它把"这一步
做什么"定型，产出的链交给 `press/` 逐键执行。图上它前面是四路检索的汇聚点
`merge_retrieval`，后面是链内小循环的入口 `act`。
"""

from __future__ import annotations

from .think_action import DECISION_MAX_RETRIES, choose_with_retry, think_action

__all__ = [
    "DECISION_MAX_RETRIES",
    "choose_with_retry",
    "think_action",
]
