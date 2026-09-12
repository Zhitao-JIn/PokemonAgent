"""brain/interface 包统一出口：大脑的港口（`BrainPort`）+ 它内嵌的数据形状
（`ActionFromBrain`/`EpisodeSummary`/`GoalForBrain`/`RunPlan`/
`StepVerifyVerdict`/`TaskForBrain`，以及 `MAX_RATIONALE`/`MAX_TIMES`/
`MAX_SEGMENTS` 三个常量）。

`BrainPort` 原来放在顶层 `pokemon_agent/interfaces/brain/`；六个数据形状原来
分别放在 `schemas/brain/domain/` 下——都跟着"协议物理挨着它自己的实现/数据
形状"这条原则搬到了这里。

**这几个数据形状立即加载，`BrainPort` 懒加载**：跟 `world/interface` 的
`WorldPort`/`Facts` 同一个道理——`brain_port.py` 要 `import
pokemon_agent.schemas.brain`（拿 `ChooseOnceReq` 等通信协议），而
`schemas/brain/communication/*.py` 里这些通信协议的字段又要从这里拿回
`GoalForBrain`/`ActionFromBrain` 等数据形状。两条依赖在初始化顺序上正面
相撞：`schemas.brain` 聚合 `__init__` 走到某个 communication 文件那一行时，
如果这里连 `BrainPort` 一起立即导入，就会在 `schemas.brain` 自己还没跑完的
时候被回头要 `ChooseOnceReq` 之类还没绑定的名字，直接炸成
`ImportError: cannot import name ... from partially initialized module`。
数据形状本身（六个 + 三个常量）零依赖，可以放心立即导入；`BrainPort` 推迟到
真的有人访问 `.BrainPort` 时才导入，两头都不用再对导入顺序小心翼翼。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain import (
    MAX_RATIONALE,
    MAX_SEGMENTS,
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
    from .brain_port import BrainPort

__all__ = [
    "MAX_RATIONALE",
    "MAX_SEGMENTS",
    "MAX_TIMES",
    "ActionFromBrain",
    "ActionSegmentFromBrain",
    "BrainPort",
    "EpisodeSummary",
    "GoalForBrain",
    "RunPlan",
    "StepVerifyVerdict",
    "TaskForBrain",
]


def __getattr__(name: str):
    if name == "BrainPort":
        from .brain_port import BrainPort as _BrainPort

        globals()["BrainPort"] = _BrainPort
        return _BrainPort
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
