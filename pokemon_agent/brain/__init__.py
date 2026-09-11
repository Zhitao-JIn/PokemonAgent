"""brain 包：纯决策层。无状态——每一步的全部输入来自参数，全部记忆来自工具调用。

- `interface/`：这个子系统的港口（`BrainPort`）+ 它内嵌的数据形状
  （`ActionFromBrain`/`EpisodeSummary`/`GoalForBrain`/`RunPlan`/
  `StepVerifyVerdict`/`TaskForBrain`），跟"怎么决策"的实现物理分开
- `brain.py`：`BrainPort` 的唯一实现（`Brain`）

本文件是统一出口：消费方只写 `from pokemon_agent.brain import X`，不深到
模块文件。

**数据形状立即加载，`Brain`/`BrainPort` 都懒加载。** 原因跟
`world/__init__.py` 对 `WorldPort` 的处理一模一样：`brain.py`（`Brain` 的
实现）要 `from pokemon_agent.schemas.brain import (ChooseOnceReq, ...)`，
而 `schemas/brain/communication/*.py` 里这些协议的字段又要从
`brain.interface` 拿回 `GoalForBrain`/`ActionFromBrain` 等数据形状——如果
这里在包初始化时就把 `Brain`/`BrainPort` 也一并导入，`schemas.brain` 跟
这个包之间就会形成真正的循环导入。`__getattr__` 把这两个名字改成按需导入，
`from pokemon_agent.brain import X` 用起来和之前一模一样，只是不再是包
初始化时就全量加载。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .interface import (
    MAX_RATIONALE,
    MAX_TIMES,
    ActionFromBrain,
    ActionSegmentFromBrain,
    EpisodeSummary,
    GoalForBrain,
    RunPlan,
    StepVerifyVerdict,
    TaskForBrain,
)

if TYPE_CHECKING:
    from .brain import Brain
    from .interface import BrainPort

__all__ = [
    "MAX_RATIONALE",
    "MAX_TIMES",
    "ActionFromBrain",
    "ActionSegmentFromBrain",
    "Brain",
    "BrainPort",
    "EpisodeSummary",
    "GoalForBrain",
    "RunPlan",
    "StepVerifyVerdict",
    "TaskForBrain",
]

_LAZY: dict[str, tuple[str, str]] = {
    "Brain": (".brain", "Brain"),
    "BrainPort": (".interface", "BrainPort"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
