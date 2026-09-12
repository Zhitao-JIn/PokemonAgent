"""`RunHarness`：一个 run 的**外部调用面**——薄类，只装轮子不做决定。

## 它为什么还留着（D1 的落地形态）

`EpisodeHarness` 在步 3 消失了（没有外部调用面：只被 `RunHarness` 用），而
`RunHarness` 留着——**它有外部调用面**：`api.py` 持有 `handle.harness` 并调
`run()` / `latest_goals()` / `submit_edit()` / `submit_human_note()`，`experiment/real_check/*`
调 `run()` / `resume_run()`。这些是"长命对象 + 前后端交互"的职责，不是图节点的职责：
节点是纯函数（`(state, runtime) -> dict`），而前后端需要一个**跨请求活着**的句柄。

## 它里面只有四件事

1. `__init__`：收下 `HarnessDeps`（**全图唯一的 context**，D3/F10）、编译一次图；
2. 两个图外入口的转调：`run()` → `run_entry.new_run`，`resume_run()` → `run_entry.resume_run`
   （**图外的开局/恢复编排在那两个函数里**，本类一行逻辑都不加）；
3. 三个薄委托给 `data_center`（观测台用：`latest_goals` / `submit_human_note` / `submit_edit`）；
4. `_compile()`：把"图长什么样"交给 `run/run_graph.py`。

**依赖只有一个入口：`deps`**（步 4 收口）：原先构造参数里那些 `trace` / `brain_tool` /
`reviewer` / `checkpoint` / 两个开关，全都已经是 `HarnessDeps` 的字段——再收一遍
就有两份真源，而"两边指的不是同一个对象"这类错**不报错**（step 4 之前
`build.py` 必须手工保证两边一致，正是这条的代价）。
"""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Task
from pokemon_agent.schemas.frontend import FromFrontendToRunHarnessSubmitEditReq
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp

from ..deps import HarnessDeps
from ..run_data_center import RunDataCenter
from .run_entry import new_run, resume_run
from .run_graph import compile_run_graph


class RunHarness:
    """run 级图的**外部调用面**：完整一局游戏（run_id），目标栈驱动，episode 为子图。

    （原 `HarnessPort` 那张 Protocol 的落地形态——Port 本身已在步 4 删除，D5：
    实现方就在隔壁文件，"港口"的定义却是"实现方在系统之外"。）
    """

    def __init__(self, deps: HarnessDeps) -> None:
        """前置条件：`deps` 非空（装配点在 `build.py`，那里也是唯一的 new 处）。

        `deps.data_center` 缺省时**在这里落实成一个真实例**：`plan`/`review` 两个
        节点要读写它的 goals/review 槽，`api.py` 也从 `handle.data_center` 读同一份
        ——不落实的话两边各看各的（`None` 或两个不同实例），而**表现只是"前端看不到
        请求、图却照跑"**，不报错。写回 `deps` 是为了让图内节点与外部调用面拿到的是
        同一个对象，不是两份。
        """
        assert deps is not None, "RunHarness needs the shared HarnessDeps"
        if deps.data_center is None:
            deps.data_center = RunDataCenter()
        self.deps = deps
        self.data_center = deps.data_center
        self._graph = self._compile()

    # ---- 入口（图外编排在 run_entry）----

    def run(
        self, run_id: str, goals: list[Task]
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """跑完一个 run，返回 run 级结算 `(outcomes, total, succeeded, success_rate)`。

        编排（RUN_START → 进图 → 取结算/RUN_END，异常补 RUN_ERROR）在
        `run_entry.new_run`——本方法只是一道**外部调用面**。
        """
        return new_run(self.deps, self._graph, run_id=run_id, goals=goals)

    def resume_run(
        self, run_id: str, episode_id: str, step: int
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """从 `(run_id, episode_id, step)` 定位的 checkpoint 恢复并跑完。

        编排（锚点读取 → DataCenter 重建 → 进图 → CHECKPOINT_RESTORE → 取结算）在
        `run_entry.resume_run`。
        """
        return resume_run(self.deps, self._graph, run_id=run_id, episode_id=episode_id, step=step)

    # ---- 运行时观测/编辑（观测台用；都是对 data_center 的薄委托）----

    def latest_goals(self) -> list[Task]:
        """最近一次 plan 的目标栈快照（栈顶 = 最后一个）；run 未开始过为空。

        快照在 plan 出口记录：栈只在 reflect（弹）/ plan（压）/ review（压）变化，
        重试轮（reflect→dispatch）栈不变，所以快照在重试期间依然准确；最多滞后
        一个"刚弹栈还没到下一轮 plan"的窗口。

        **薄委托**：真正的状态在 `self.data_center`——新代码应该直接读写它，
        这个方法留着只是不破坏 `api.py` 现有的调用形状。
        """
        return self.data_center.latest_goals()

    def submit_human_note(self, text: str) -> None:
        """薄委托：把人类实时插话转给 `self.data_center`（同一份实例也给了
        `think_action`，那边的决策每步取一次）。API 层可以调这个方法，也可以直接写
        `handle.data_center.submit_human_note(...)`——两者等价，跟
        `submit_edit`/`data_center.submit_goals_edit` 是同一个薄委托模式。
        """
        self.data_center.submit_human_note(text)

    def submit_edit(self, edit: FromFrontendToRunHarnessSubmitEditReq) -> None:
        """收一条目标栈编辑指令进单槽（最新覆盖），plan 轮消费生效。

        `FromFrontendToRunHarnessSubmitEditReq`（只剩一种：整栈原子替换，不锁栈顶）
        在消费时才真正应用（`run/plan.py::apply_goals_edit`）。同上，薄委托
        给 `self.data_center`。
        """
        self.data_center.submit_goals_edit(edit)

    # ---- 图组装 ----

    def _compile(self) -> CompiledStateGraph:
        """把"图长什么样"交给 `run/run_graph.py`——本方法只留一句转调。

        拓扑（`dispatch → episode → reflect`，含 `reflect` 出口的重试判据、
        `plan` 出口三路、`START` 的恢复分流，以及挂在 `episode` 那格上的
        `error_handler`）全在 `run/run_graph.py`；**步 4 起它不再收 nodes 参数**
        （节点就是同级的 6 个模块）。
        """
        return compile_run_graph()


__all__ = ["RunHarness"]
