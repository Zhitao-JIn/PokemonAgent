"""harness 包：控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。

**两张图 + 一个共用 context**（`docs/spec/harness/SPEC.md` 第二、三节）：

- `run/`：**run 级图**（一个 run = 完整一局游戏），**包根只放骨架、5 个节点住
  `nodes/`**（v16：与 `episode/<功能域>/<节点>.py` 同深）——
  节点是 `nodes/begin.py`/`nodes/plan.py`/`nodes/dispatch.py`/`nodes/episode.py`/
  `nodes/review.py`（**文件名 = `run_graph.py` 里 `add_node` 的字面量**，§5.3-⑤；
  **`reflect` 0914 控制台改造已删，其活并入 `review`**），装配在
  `run/run_graph.py`，图外侧门（`new_run`）在 `run/run_entry.py`，
  唯一的状态载体是 `run/run_state.py`，**外部调用面**是
  `run/harness.py` 的薄类 `RunHarness`（策略常量已全部收进顶层
  `pokemon_agent/config.py`，包内各节点直接 import config）
- `episode/`：**episode 级图**（run 图的子图），21 个节点按七个功能域
  （`open/ gate/ retrieve/ decide/ press/ store/ close/`）分文件夹，装配在
  `episode/episode_graph.py`，图外侧门在 `episode/episode_entry.py`，
  唯一的状态载体是 `episode/episode_state.py`
- `deps.py`：**全图唯一的 context**（`HarnessDeps`）——它不属于任何一张图，
  两图与图外两个入口共用同一个对象
- `interface/`：这个子系统**真的**需要外面给的东西——`Planner`（plan 位置的
  input 来源）与 `Reviewer`（插话 + 审），外加 `Planner` 的入参/产出模型
  （`PlannerContext` / `PlannerOutcome`）。两张"镜子"
  （`HarnessPort`/`EpisodeHarnessPort`）已在步 4 删除、状态与常量各归其位（§3.4）
- `console_reviewer.py` / `console_planner.py`：控制台上的两个实现（读 stdin）
- `brain_planner.py`：`BrainPlanner`——**模型侧**的 `Planner`（默认装配，0914 S2）
- `null_reviewer.py`：`NullReviewer` / `NullPlanner`——不接策略对象时的默认实现
  （取代了旧的 `AutoContinueReviewer` / `RunInteraction` 那一套）
- **写账共用件已不在根下（步 5 销账）**：D8-③ 把它下沉到 `tools/trace/model_calls.py`，
  端口那边多了 `append_model_calls(req)`。所以根下只剩五个 `.py`。

本文件是统一出口：对外只从这里 import；包内模块之间走相对 import。

**0914 控制台改造删掉了 `interaction.py` 与 `auto_reviewer.py`**，随之一并删掉的
是那套**懒加载 `__getattr__` 机制**：它当初存在，只因为 `HumanReviewer` 要 import
`schemas.harness`、而后者又要回头从这里拿 `HumanDecision`，形成初始化循环。
现在 `interface/` 只剩两个零依赖的 Protocol，循环不存在了，于是全部改成
**立即导入**——用起来一样，但少一层"名字什么时候才存在"的心智负担。
"""

from __future__ import annotations

from .brain_planner import BrainPlanner
from .deps import HarnessDeps
from .interface import GoalUpdate, Planner, PlannerContext, PlannerOutcome, Reviewer
from .run.harness import RunHarness
from .run.run_state import RunState

__all__ = [
    "BrainPlanner",
    "GoalUpdate",
    "HarnessDeps",
    "Planner",
    "PlannerContext",
    "PlannerOutcome",
    "Reviewer",
    "RunHarness",
    "RunState",
]
