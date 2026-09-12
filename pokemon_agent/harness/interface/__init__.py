"""harness/interface 包统一出口：harness 层的两张港口（`HarnessPort`/
`EpisodeHarnessPort`）+ `HumanReviewer`，以及它们各自内嵌的数据形状
（`RunState`/`ResumeEpisode`/`EpisodeRunState`/`HumanDecision`）和三个
常量（`MAX_GOAL_RETRIES`/`MAX_PLAN_PUSH`/`PLAN_MAX_ATTEMPTS`）。

三个 Port 原来放在顶层 `pokemon_agent/interfaces/harness/`；`HumanDecision`
原来放在 `schemas/harness/domain/`——都跟着"协议物理挨着它自己的实现/数据
形状"这条原则搬到了这里。

**`HumanDecision` 立即加载，其余全部懒加载**：跟 `world/interface` 的
`WorldPort`/`brain/interface` 的 `BrainPort` 同一个道理——`harness_port.py`/
`episode_harness_port.py`/`human_reviewer.py` 都要
`import pokemon_agent.schemas.harness`，而
`schemas/harness/communication/FromHarnessToReviewerReviewResp.py` 的字段
又要从这里拿回 `HumanDecision`。两条依赖在初始化顺序上正面相撞：
`schemas.harness` 聚合 `__init__` 走到这个 communication 文件那一行时，
如果这里把 `HarnessPort`/`EpisodeHarnessPort`/`HumanReviewer`/`RunState`/
`ResumeEpisode`/`EpisodeRunState`/三个常量也一起立即导入，就会在
`schemas.harness` 自己还没跑完的时候被回头要还没绑定的名字，直接炸成
`ImportError: cannot import name ... from partially initialized module`。
`HumanDecision` 零依赖，可以放心立即导入；其余全部（三个 Port + 它们各自
模块里定义的状态模型/常量）推迟到真的有人访问时才导入。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .domain import HumanDecision

if TYPE_CHECKING:
    from pokemon_agent.harness.episode.state import EpisodeRunState
    from pokemon_agent.harness.run.state import ResumeEpisode, RunState

    from .episode_harness_port import EpisodeHarnessPort
    from .harness_port import MAX_GOAL_RETRIES, MAX_PLAN_PUSH, PLAN_MAX_ATTEMPTS, HarnessPort
    from .human_reviewer import HumanReviewer

__all__ = [
    "MAX_GOAL_RETRIES",
    "MAX_PLAN_PUSH",
    "PLAN_MAX_ATTEMPTS",
    "EpisodeHarnessPort",
    "EpisodeRunState",
    "HarnessPort",
    "HumanDecision",
    "HumanReviewer",
    "ResumeEpisode",
    "RunState",
]

_LAZY: dict[str, tuple[str, str]] = {
    "EpisodeHarnessPort": (".episode_harness_port", "EpisodeHarnessPort"),
    "EpisodeRunState": ("pokemon_agent.harness.episode.state", "EpisodeRunState"),
    "MAX_GOAL_RETRIES": (".harness_port", "MAX_GOAL_RETRIES"),
    "MAX_PLAN_PUSH": (".harness_port", "MAX_PLAN_PUSH"),
    "PLAN_MAX_ATTEMPTS": (".harness_port", "PLAN_MAX_ATTEMPTS"),
    "HarnessPort": (".harness_port", "HarnessPort"),
    "ResumeEpisode": ("pokemon_agent.harness.run.state", "ResumeEpisode"),
    "RunState": ("pokemon_agent.harness.run.state", "RunState"),
    "HumanReviewer": (".human_reviewer", "HumanReviewer"),
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
