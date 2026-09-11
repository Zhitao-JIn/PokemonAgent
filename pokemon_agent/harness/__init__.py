"""harness 包：控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。

- `interface/`：这个子系统的两张港口（`HarnessPort`/`EpisodeHarnessPort`）+
  `HumanReviewer`，以及它们各自内嵌的数据形状（`RunState`/`ResumeEpisode`/
  `EpisodeRunState`/`HumanDecision`）和三个常量（`MAX_GOAL_RETRIES`/
  `MAX_PLAN_PUSH`/`PLAN_MAX_ATTEMPTS`），跟"怎么跑图"的实现物理分开
- `run_harness.py`：`RunHarness`——主 agent，跑完整一局游戏
- `episode_harness.py`：`EpisodeHarness`——子 agent，解栈顶一个 goal
- `run_data_center.py`：`RunDataCenter` / `DataCenterReviewer`——前后端交互中间层
- `auto_reviewer.py`：`AutoContinueReviewer`——不注入 reviewer 时的默认放行者
- `episode_utils.py`/`run_utils.py`：图控制本身用到的纯函数，不绑定任何一根依赖
- `game_utils.py`/`brain_utils.py`/`memory_query_utils.py`/`run_plan_utils.py`：
  episode/run 两级图分别与 game/brain/memory/plan 各根依赖交互专用的重试与
  记账工具——一根依赖一个文件，都不进出口

本文件是统一出口：对外只从这里 import；包内模块之间走相对 import。

**`HumanDecision` 立即加载，其余全部懒加载。** 跟 `world/__init__.py` 对
`WorldPort`/`brain/__init__.py` 对 `Brain`/`BrainPort` 同一个道理：
`episode_harness.py`/`run_harness.py` 这些实现文件、以及 `interface/` 里的
三个 Port，都要 `import pokemon_agent.schemas.harness`，而
`schemas/harness/communication/FromHarnessToReviewerReviewResp.py` 的字段
又要从这里拿回 `HumanDecision`。如果这里在包初始化时就把 `RunHarness`/
`EpisodeHarness`/三个 Port/状态模型也一并导入，`schemas.harness` 跟这个包
之间就会形成真正的循环导入。`__getattr__` 把这些名字改成按需导入，
`from pokemon_agent.harness import X` 用起来和之前一模一样，只是不再是包
初始化时就全量加载。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .interface import HumanDecision

if TYPE_CHECKING:
    from .auto_reviewer import AutoContinueReviewer
    from .episode_harness import STALL_LIMIT, EpisodeHarness
    from .interface import (
        MAX_GOAL_RETRIES,
        MAX_PLAN_PUSH,
        PLAN_MAX_ATTEMPTS,
        EpisodeHarnessPort,
        EpisodeRunState,
        HarnessPort,
        HumanReviewer,
        ResumeEpisode,
        RunState,
    )
    from .run_data_center import DataCenterReviewer, RunDataCenter
    from .run_harness import RunHarness

__all__ = [
    "MAX_GOAL_RETRIES",
    "MAX_PLAN_PUSH",
    "PLAN_MAX_ATTEMPTS",
    "STALL_LIMIT",
    "AutoContinueReviewer",
    "DataCenterReviewer",
    "EpisodeHarness",
    "EpisodeHarnessPort",
    "EpisodeRunState",
    "HarnessPort",
    "HumanDecision",
    "HumanReviewer",
    "ResumeEpisode",
    "RunDataCenter",
    "RunHarness",
    "RunState",
]

_LAZY: dict[str, tuple[str, str]] = {
    "AutoContinueReviewer": (".auto_reviewer", "AutoContinueReviewer"),
    "STALL_LIMIT": (".episode_harness", "STALL_LIMIT"),
    "EpisodeHarness": (".episode_harness", "EpisodeHarness"),
    "DataCenterReviewer": (".run_data_center", "DataCenterReviewer"),
    "RunDataCenter": (".run_data_center", "RunDataCenter"),
    "RunHarness": (".run_harness", "RunHarness"),
    "MAX_GOAL_RETRIES": (".interface", "MAX_GOAL_RETRIES"),
    "MAX_PLAN_PUSH": (".interface", "MAX_PLAN_PUSH"),
    "PLAN_MAX_ATTEMPTS": (".interface", "PLAN_MAX_ATTEMPTS"),
    "EpisodeHarnessPort": (".interface", "EpisodeHarnessPort"),
    "EpisodeRunState": (".interface", "EpisodeRunState"),
    "HarnessPort": (".interface", "HarnessPort"),
    "HumanReviewer": (".interface", "HumanReviewer"),
    "ResumeEpisode": (".interface", "ResumeEpisode"),
    "RunState": (".interface", "RunState"),
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
