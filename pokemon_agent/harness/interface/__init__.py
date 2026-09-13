"""harness/interface 包统一出口：harness 层**真端口**——`HumanReviewer` 与它的数据形状
`HumanDecision`。

**判据：港口 = 实现方在系统之外**（`PLAN_graph_composition.md` §3.4）。这里曾经住着
两张"镜子"——`HarnessPort`/`EpisodeHarnessPort`，实现方就是隔壁文件的
`RunHarness`/`EpisodeHarness`；D5 已删（步 4：653 行零信息量的抄本，20 个方法全是
`...`，而"图有哪些节点"由 `episode_graph.py` 的 `add_node` 说、"节点改哪一处"由那张
21 行职责表说，都**可执行/可核对**）。同一次收口里搬走的还有：

- `RunState` → `run/run_state.py`（状态不是能力）；
- `EpisodeRunState` → `episode/episode_state.py`；
- 三个常量（`MAX_GOAL_RETRIES`/`MAX_PLAN_PUSH`/`BRAIN_MAX_ATTEMPTS`）→ 顶层
  `pokemon_agent/config.py`（它们与其余策略常量同族，集中一处才好调实验参数）；
  包出口**不再**再导出常量——需要的人直接 `from pokemon_agent.config import X`。

一句话：`interface/` 从此只回答"harness 需要外面给什么"，不再回答"harness 自己长
什么样"。

**`HumanDecision` 立即加载，`HumanReviewer` 懒加载**：后者要
`import pokemon_agent.schemas.harness`，而
`schemas/harness/communication/FromHarnessToReviewerReviewResp.py` 的字段又要从这里
拿回 `HumanDecision`。两条依赖在初始化顺序上正面相撞：`schemas.harness` 聚合 `__init__`
走到这个 communication 文件那一行时，如果这里也把 `HumanReviewer` 一并立即导入，就会在
`schemas.harness` 自己还没跑完的时候被回头要还没绑定的名字，直接炸成
`ImportError: cannot import name ... from partially initialized module`。
`HumanDecision` 零依赖（一个 `str` 枚举），可以放心立即导入。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .domain import HumanDecision

if TYPE_CHECKING:
    from .human_reviewer import HumanReviewer

__all__ = [
    "HumanDecision",
    "HumanReviewer",
]

_LAZY: dict[str, tuple[str, str]] = {
    "HumanReviewer": (".human_reviewer", "HumanReviewer"),
}


def __getattr__(name: str) -> object:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
