"""`ConsolePlanner`：控制台上的 `Planner` 实现——**让人写出一版规划**。

**它和 `ConsoleReviewer` 是分工不同的两个控制台实现**（用户 0914 定调）：

| | `ConsolePlanner.plan` | `ConsoleReviewer.inject` |
|---|---|---|
| 做什么 | **从零给出一版**（新目标 + 对已有条目的表态） | 对**已有的一版**说一句"不对" |
| 什么时候 | plan 节点、目标表空了/要重规划 | LLM 出完结构体之后（plan / think_action / judge） |
| 回什么 | `PlannerOutcome`（未落表） | 一句自然语言（可空） |

两者都读 stdin，但**不共用读行代码**：`ConsolePlanner` 要**循环读多行**
（一个目标一行），`ConsoleReviewer` 只读一两次。硬凑一个基类只会让两边的
"退出条件"纠缠在一起。

**为什么 `plan()` 不做超时**：`Reviewer` 的超时是"人等不到就算了、按没意见继续"
——因为**表态是可选的**。但 `plan` 的产出是**目标表本身**：没人给目标，
这一版就是空的，表末检立刻判 done、run 当场收尾。一个"静默的 30 秒空转"
比让人明说"我不加了"更糟。所以这里**老老实实阻塞读**，用一行空行表达
"这一版我不加目标、也不改条目"（和 `NullPlanner` 等价，但这是人**主动**说的）。

**它和插话的关系**：`plan` 节点里的顺序是"先问 `Planner` 要一版 → 再给人看这一版、
收插话（`Reviewer.inject`）→ 落表"。`ConsolePlanner` 只负责第一步；第二步由节点调
`ConsoleReviewer.inject()`。**两个控制台实现组合起来 = "人写一版、再自己点头"**
——听着绕，但意义在于：写的时候人可能只写了个大概，看到落表后的正式结构才发现
少了一条。

**0914 S2**：输入面跟着 `PlannerContext` 一起换了——现在会先把**局索引**（本 run
每一局的成败与步数）打给人看，人写目标时看得见前面几局成没成；返回值也从
"条目列表"升成 `PlannerOutcome`（新增 + 定点更新 + 收手判定），人因此能表达
"这条我不做了"（`放弃`）与"这条重开"（`重开`）——那是 `GoalStatus` 权限表里
唯一允许人直接写的两个状态。
"""

from __future__ import annotations

import sys

from pokemon_agent.brain import Task
from pokemon_agent.schemas.harness.domain import GoalEntry, GoalStatus

from .interface.planner_context import PlannerContext
from .interface.planner_outcome import GoalUpdate, PlannerOutcome

_ABANDON_WORDS = {"放弃", "abandon", "abandoned"}
_RETRY_WORDS = {"重开", "重试", "retry", "pending"}


class ConsolePlanner:
    """控制台实现：让人一个目标一行地写出这一版规划。

    **输入格式**（两种行，混着写也行）：

    ```
    目标描述 | 完成条件 | 父目标序号          # 新目标
    @序号 放弃|重开 理由                       # 改已有条目（例：@2 放弃 门锁着打不开）
    ```

    - 第一段（描述）必填；空行 = **这一版不加任何新目标**；
    - 第二段缺省时复用第一段（完成条件与描述同）；
    - 第三段是这个目标挂在哪条**已有**目标下面（填上面渲染出来的序号，从 0 起）；
      留空 = 顶层目标。

    输入以一行 `---`（或 EOF）结束。

    **为什么用管道分隔而不是让人写 JSON**：这是一个手打入口，
    让人去数引号和括号等于劝退。三段以内、可省略、空行可退——这三条就是全部规则。
    """

    def __init__(self, max_steps_default: int = 400) -> None:
        """构造。

        max_steps_default：手打入口没有"步数上限"这一栏（人不知道该填多少），
            于是由实现给一个统一默认值。`Task.max_steps > 0` 是它的硬约束。
        """
        self._max_steps_default = max_steps_default

    def plan(self, ctx: PlannerContext) -> PlannerOutcome:
        """把当前表与局索引亮出来，读人写的这一版规划。

        后置条件：返回**未落表**的 `PlannerOutcome`——`entries` 的 status 一律
            `PENDING`、`parent_id` 已按输入解析好；`updates` 的 `status` 只可能是
            `ABANDONED` / `PENDING`（权限表允许人写的那两个）。人直接回空行则
            返回空产出。
        """
        self._render_context(ctx)
        print(
            "\n=== 请你给出这一版规划 ===\n"
            "  新目标：  一行一个，格式：  目标描述 | 完成条件 | 父目标序号\n"
            "  改已有：  @序号 放弃|重开 理由        （例：@2 放弃 门锁着打不开）\n"
            "  完成条件可省略（默认同描述）；父目标序号可省略（默认顶层）。\n"
            "  直接回车 = 这一版不加目标也不改条目；输入 --- 结束。\n"
        )
        raw_lines = self._read_lines()
        entries = self._parse_lines(raw_lines, ctx.plan)
        updates = self._parse_updates(raw_lines, ctx.plan)
        for update in updates:
            print(f"  ~ [{update.task_id}] → {update.status.value}（{update.note}）")
        for entry in entries:
            parent = entry.parent_id or "top"
            print(f"  + [{parent}] {entry.task.goal}（判据：{entry.task.success_criteria}）")
        return PlannerOutcome(entries=entries, updates=updates)

    # ---- 内部 ----

    @staticmethod
    def _render_context(ctx: PlannerContext) -> None:
        """把目标表与局索引打印给人（人的决策要看得见前面几局成没成）。"""
        print(f"\n--- 局索引（run {ctx.run_id}，按执行顺序）---")
        if not ctx.index:
            print("  （本 run 还没跑完任何一局）")
        for memory in ctx.index:
            mark = "成功" if memory.success else "失败"
            print(f"  {memory.episode_id}  {mark}  {memory.goal}（{memory.steps} 步）")

        print(f"\n--- 目标表（run {ctx.run_id}）---")
        if not ctx.plan:
            print("  （空表——这是第一次规划）")
            return
        for index, entry in enumerate(ctx.plan):
            parent = f" ← {entry.parent_id}" if entry.parent_id else ""
            tried = f"  [已试 {entry.attempts} 次]" if entry.attempts else ""
            note = f"  · {entry.note}" if entry.note else ""
            print(f"  {index:>3}  {entry.status.value:<9} {entry.task.goal}{parent}{tried}{note}")

    @staticmethod
    def _read_lines() -> list[str]:
        """读若干行，遇空行、`---` 或 EOF 结束。

        后置条件：返回逐行 `strip()` 过的非空文本。
        """
        lines: list[str] = []
        while True:
            try:
                line = sys.stdin.readline()
            except (EOFError, ValueError):
                break
            if line == "":
                break
            stripped = line.strip()
            if stripped == "" or stripped == "---":
                break
            lines.append(stripped)
        return lines

    def _parse_lines(self, lines: list[str], existing: list[GoalEntry]) -> list[GoalEntry]:
        """把若干行解析成 `GoalEntry`（`PENDING`、未落表）。

        前置条件：`existing` 是当前表（用来把父目标序号解析成 `task_id`）。
        后置条件：每条的 `task.goal` / `success_criteria` 都非空。
        """
        entries: list[GoalEntry] = []
        for line in lines:
            if line.startswith("@"):
                continue
            parts = [part.strip() for part in line.split("|")]
            goal = parts[0]
            if not goal:
                continue
            criteria = parts[1] if len(parts) > 1 and parts[1] else goal
            parent_index = parts[2] if len(parts) > 2 else ""
            parent_id: str | None = None
            if parent_index.isdigit():
                index = int(parent_index)
                if 0 <= index < len(existing):
                    parent_id = existing[index].task.task_id
            entries.append(
                GoalEntry(
                    task=Task(
                        task_id=f"goal-{len(entries) + 1}",
                        goal=goal,
                        success_criteria=criteria,
                        max_steps=self._max_steps_default,
                    ),
                    status=GoalStatus.PENDING,
                    parent_id=parent_id,
                )
            )
        return entries

    @staticmethod
    def _parse_updates(lines: list[str], existing: list[GoalEntry]) -> list[GoalUpdate]:
        """把 `@序号 放弃|重开 理由` 那几行解析成定点更新。

        后置条件：只产出 `ABANDONED`（放弃）/ `PENDING`（重开）两个状态——那是
            `GoalStatus` 权限表里允许人写的全部；序号越界、词不认识、字段不足的行
            **跳过**（手打入口，写错一行不该让整版作废）。
        """
        updates: list[GoalUpdate] = []
        for line in lines:
            if not line.startswith("@"):
                continue
            parts = line.removeprefix("@").split(maxsplit=2)
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            index = int(parts[0])
            if not 0 <= index < len(existing):
                continue
            word = parts[1]
            if word in _ABANDON_WORDS:
                status = GoalStatus.ABANDONED
            elif word in _RETRY_WORDS:
                status = GoalStatus.PENDING
            else:
                continue
            note = parts[2] if len(parts) > 2 else ""
            updates.append(
                GoalUpdate(task_id=existing[index].task.task_id, status=status, note=note)
            )
        return updates


__all__ = ["ConsolePlanner"]
