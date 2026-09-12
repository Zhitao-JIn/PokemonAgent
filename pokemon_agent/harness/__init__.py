"""harness 包：控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。

**两张图 + 一个共用 context**（`docs/spec/harness/PLAN_graph_composition.md` §3.1）：

- `run/`：**run 级图**（一个 run = 完整一局游戏），6 个节点平铺在包根——
  节点是 `begin.py`/`plan.py`/`dispatch.py`/`episode.py`/`reflect.py`/`review.py`
  （**文件名 = `run_graph.py` 里 `add_node` 的字面量**，§5.3-⑤），装配在
  `run/run_graph.py`，图外侧门（`new_run`/`resume_run`，以及 `recursion_limit` 那个常量）
  在 `run/run_entry.py`，唯一的状态载体是 `run/run_state.py`，**外部调用面**是
  `run/harness.py` 的薄类 `RunHarness`
- `episode/`：**episode 级图**（run 图的子图），21 个节点按七个功能域
  （`open/ gate/ retrieve/ decide/ press/ store/ close/`）分文件夹，装配在
  `episode/episode_graph.py`，图外侧门在 `episode/episode_entry.py`，
  唯一的状态载体是 `episode/episode_state.py`
- `deps.py`：**全图唯一的 context**（`HarnessDeps`）——它不属于任何一张图，
  两图与图外两个入口共用同一个对象
- `interface/`：这个子系统**真的**需要外面给的东西——`HumanReviewer`（前端实现）
  与 `HumanDecision`。两张"镜子"（`HarnessPort`/`EpisodeHarnessPort`）已在步 4 删除、
  状态与常量各归其位（§3.4）
- `run_data_center.py`：`RunDataCenter` / `DataCenterReviewer`——前后端交互中间层
- `auto_reviewer.py`：`AutoContinueReviewer`——不注入 reviewer 时的默认放行者
- **写账共用件已不在根下（步 5 销账）**：D8-③ 把它下沉到 `tools/trace/model_calls.py`，
  端口那边多了 `append_model_calls(req)`。所以根下只剩四个 `.py`，且是终态。

本文件是统一出口：对外只从这里 import；包内模块之间走相对 import。

**`HumanDecision` 立即加载，其余全部懒加载。** 跟 `world/__init__.py` 对
`WorldPort`/`brain/__init__.py` 对 `Brain`/`BrainPort` 同一个道理：`run/harness.py`
这些实现文件、以及 `interface/human_reviewer.py`，都要
`import pokemon_agent.schemas.harness`，而
`schemas/harness/communication/FromHarnessToReviewerReviewResp.py` 的字段
又要从这里拿回 `HumanDecision`。如果这里在包初始化时就把 `RunHarness`/
状态模型也一并导入，`schemas.harness` 跟这个包
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
    from .deps import HarnessDeps
    from .episode.episode_state import EpisodeRunState
    from .episode.press import STALL_LIMIT
    from .interface import HumanReviewer
    from .run.harness import RunHarness
    from .run.plan import MAX_PLAN_PUSH, PLAN_MAX_ATTEMPTS
    from .run.reflect import MAX_GOAL_RETRIES
    from .run.run_state import ResumeEpisode, RunState
    from .run_data_center import DataCenterReviewer, RunDataCenter

__all__ = [
    "MAX_GOAL_RETRIES",
    "MAX_PLAN_PUSH",
    "PLAN_MAX_ATTEMPTS",
    "STALL_LIMIT",
    "AutoContinueReviewer",
    "DataCenterReviewer",
    "EpisodeRunState",
    "HarnessDeps",
    "HumanDecision",
    "HumanReviewer",
    "ResumeEpisode",
    "RunDataCenter",
    "RunHarness",
    "RunState",
]

_LAZY: dict[str, tuple[str, str]] = {
    "AutoContinueReviewer": (".auto_reviewer", "AutoContinueReviewer"),
    "STALL_LIMIT": (".episode.press", "STALL_LIMIT"),
    "HarnessDeps": (".deps", "HarnessDeps"),
    "DataCenterReviewer": (".run_data_center", "DataCenterReviewer"),
    "RunDataCenter": (".run_data_center", "RunDataCenter"),
    "RunHarness": (".run.harness", "RunHarness"),
    "MAX_GOAL_RETRIES": (".run.reflect", "MAX_GOAL_RETRIES"),
    "MAX_PLAN_PUSH": (".run.plan", "MAX_PLAN_PUSH"),
    "PLAN_MAX_ATTEMPTS": (".run.plan", "PLAN_MAX_ATTEMPTS"),
    "EpisodeRunState": (".episode.episode_state", "EpisodeRunState"),
    "HumanReviewer": (".interface", "HumanReviewer"),
    "ResumeEpisode": (".run.run_state", "ResumeEpisode"),
    "RunState": (".run.run_state", "RunState"),
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
