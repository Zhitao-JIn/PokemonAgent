"""`GoalEntry` / `GoalStatus`：run 级目标表的一行（跨层契约，与 `TraceEvent` 同级）。

**它取代了什么**：原先 `RunState` 上是两个平行列表——`goals: list[Task]` +
`attempts: list[int]`，靠一条 `len(attempts) == len(goals)` 的 invariant 手动保持同步。
两个平行列表要**靠纪律**保持对齐，这本身就是设计味道；收敛成一条记录后，那条
invariant 从"要维护的约束"变成"结构上不可能违反"。

**为什么 `Task` 一字不改**：`status` 是 run 级**编排**概念，不是任务本体的属性。
`Task` 还出现在 `WorldPort.reset()` / `GameToolPort.reset()` 的签名里，往里塞
`status` 会把 run 级的编排词汇漏进 world。

**为什么 `parent_id` 而不是嵌套树**：目标表要**层次**（子目标知道自己在为谁服务），
但层次只用来渲染缩进与给模型读上下文，不需要真树结构。扁平表 + 一个指父指针
是最小改动：`FAILED`/`ABANDONED` 的条目**留在表里**，于是它们自动成为
①层次上下文（后续新目标可以挂上去）②教训（`note` 里存着失败理由）。

**权威设计**：`docs/PLAN_console_reviewer.md` §4 与 `docs/PLAN_planner_v2.md` §2。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task


class GoalStatus(StrEnum):
    """一条目标在 run 内的状态。

    **权限划分是这张表示意的核心**（R2「摘要不当证据：任何'必须为真'的判断走机械
    来源，不走 LLM 叙述」，与 judge/verify 的 `reason=False` 同源）：

    - `PENDING → RUNNING`：`dispatch` 选中并派发（机械）；
    - `RUNNING → COMPLETED`：**harness** 从 `outcome.success` 推导（机械事实）；
    - `RUNNING → PENDING`：**harness** 在一局失败后置回待派（不下结论）；
    - `RUNNING → FAILED`：**harness**（人审时表态放弃，或 plan 明确不再重开）；
    - 任意 → `ABANDONED`：`Planner`（人 / 将来的模型）主观放弃。

    `COMPLETED`/`FAILED` **只能由 harness 盖章**——它们是机械事实，让 LLM 或人
    直接写等于违反 R2。人能做的是**推翻 judge 的裁决**（`review` 节点的 `audit`），
    推翻之后由 harness 重新盖章。`ABANDONED` 是唯一人能直接写的状态——它是
    **主观决定**，不是事实，不归 R2 管。
    """

    PENDING = "pending"
    """待派发：还没跑过，或失败后被置回等 plan 表态。"""
    RUNNING = "running"
    """正在跑：`dispatch` 已选中、本局还没收结算。**全表至多一条**。"""
    COMPLETED = "completed"
    """本局判成功（机械事实，harness 盖章）。"""
    FAILED = "failed"
    """人（或 plan）明确放弃这个目标（`note` 里记理由）。"""
    ABANDONED = "abandoned"
    """主观放弃，还没跑或没跑完就不做了。"""

    @property
    def is_active(self) -> bool:
        """这一条还算不算"后面要做的事"——`PENDING`/`RUNNING` 才是。

        这是**定义在状态上、而不是散在节点里**的判据（原先 `dispatch.py` 的模块级
        `_ACTIVE_STATUSES` 元组就是它）。三处消费者：

        - `dispatch.active_stack()`：`episode_goals` 只投影活跃条目，且把正在跑的
          那条排在最后（子图判 `[-1]`）；
        - `plan` 的**表末检**：表里一条活跃条目都没有 + `Planner` 不新增 → done；
        - `run_graph._has_pending()` 是它的近亲但**有意不同**：那条边只问
          `PENDING`（`RUNNING` 意味着"有局在跑"，不该再派一条）。

        `COMPLETED`/`FAILED`/`ABANDONED` 都已出局，但**留在 `plan` 表里**——
        它们同时是层次上下文（子目标挂上去）与教训（`note`）。
        """
        return self in (GoalStatus.PENDING, GoalStatus.RUNNING)


class GoalEntry(BaseModel):
    """目标表的一行：一个任务 + 它在 run 内的状态与追踪信息。

    字段注释里的"权威"读法见 `docs/PLAN_console_reviewer.md` §4.3 那张权限表。
    """

    task: Task = Field(description="任务本体（brain 的领域模型，一字不改）")
    status: GoalStatus = Field(
        default=GoalStatus.PENDING,
        description="编排状态。**至多一条 `RUNNING`**（不变式，dispatch/reflect 出入口 assert）",
    )
    attempts: int = Field(
        default=0,
        description="已派发次数（原来是平行列表，现在贴着目标走）。"
        "它不再被任何上限截断——'要不要再试'是 plan 读表后的决策，不是常量",
    )
    last_episode_id: str | None = Field(
        default=None,
        description="最近一次派发 → 回查 step_memory / trace 的**指针**。"
        "`COMPLETED`/`FAILED` 的条目这一列必须非空——没有来源的状态等于不可追溯的断言",
    )
    note: str = Field(
        default="",
        description="放弃/重开的理由（人或模型给的）。弃掉的条目留表时，这一列就是**教训**",
    )
    parent_id: str | None = Field(
        default=None,
        description="父目标的 `task_id`——层次。语义是'这个新目标是为了解决那个老目标"
        "而拆出来的'。渲染层靠它算缩进（`tools/prompts/run_plan.py::goals_lines`，"
        "不再由列表下标算）。**trace 侧不用它**：`Goal`/`Task` 都不带 `parent_id`，"
        "落进 trace 的目标只有文字（见 `CHANGELOG.md` 2026-09-14 第 91 条）",
    )


__all__ = ["GoalEntry", "GoalStatus"]
