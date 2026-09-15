"""run 图的唯一状态载体：`RunState`。

从 `harness/interface/harness_port.py` 搬来——
**状态不是能力**，`interface/` 只回答"harness 需要外面给什么"。那个 Port 文件已在
步 4 删除（D5：它是"镜子"不是"港口"），所以旧的 `harness_port` 路径不再存在——
唯一的家就是这里，包出口在 `harness/__init__.py`（懒加载表）与 `run/__init__.py`。

**0914 控制台改造把 `goals` + `attempts` 两个平行列表并成了一张目标表
（`plan: list[GoalEntry]`）**：那条 `len(attempts) == len(goals)` 的不变式从
"要靠纪律维护的约束"变成"结构上不可能违反"。同时 `plan_failed` 整个字段删除
——它原来是"plan 连续调不通模型 → 交人工"的路由旗，控制台改造后
`plan` 的第一跳（要一版目标）与"人对这一版不满意"合到同一个节点里，
**机器没主意和人不满意的出口是同一条**，不再需要一个单独的旗来分叉。

**原 `ResumeEpisode` 已删**（见 `CHANGELOG.md` 2026-09-13 第 57 条）：它是"恢复分派的定位"
（`dispatch` 据此走恢复路径），随 checkpoint 恢复链一起删掉了。

**「栈」这个词已经不准了**：目标表不再是 LIFO 栈——`dispatch` 选的是
**第一条 `PENDING`**（按表序），不是表末那条。`review` 把失败目标置回 `PENDING`
后，下一次 `dispatch` 仍会挑到它（它还在表里、还是第一条待派的），
效果与旧的"压回栈顶"一样，但机制是"状态迁移"而不是"重压"。
`episode_goals` 这个**给子图的投影**因此保持"整表映射"的含义不变。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Goal, Task
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp
from pokemon_agent.schemas.harness.domain import GoalEntry


class RunState(BaseModel):
    """一个 run 的**全部**可序列化状态。

        身份    run_id / plan / outcomes           跨轮
        交接    episode_goals / task                每次派发前由 `dispatch` 写，
                                                       **键名与 episode 图逐字对上**
        流转    episode_id / outcome                单轮内，节点间传递

    **`plan` 是目标表**（不是栈）：每一行带自己的 `status` / `attempts` /
    `parent_id`。`dispatch` 选**第一条 `PENDING`**（表序，不是表末），
    `review` 盖章改状态，`plan` 节点 append 新条目。**至多一条 `RUNNING`**
    是这张表的 invariant。

    **`episode_goals` 是投影，不是第二份目标表**：它是 `plan` 里
    **非终态**条目映射成 `Goal` 之后的形态（子图要的形状），每局由 `dispatch`
    重写一次。两者是**不同的东西**，所以是两个键——领域概念一份、给子图的投影一份。

    **活对象一个都不进来**（episode harness / trace / memory / llm）：它们
    序列化不了，是 `HarnessDeps` 的字段，由装配处注入。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话），trace 按它分组")
    plan: list[GoalEntry] = Field(
        description="目标表（表序 = 派发顺序，`dispatch` 挑第一条 `PENDING`）。"
        "`COMPLETED`/`ABANDONED`/`FAILED` 的条目**留在表里**——它们是层次上下文与教训",
    )
    outcomes: list[FromRunHarnessToEpisodeHarnessRunResp] = Field(
        default_factory=list,
        description="已完成的 episode 结算（含失败局），按执行顺序——`RunResp` 的汇总源",
    )

    episode_goals: list[Goal] = Field(
        default_factory=list,
        description="**给子图的投影**：目标表里非终态条目映射成 `Goal` 的形态。"
        "每局由 `dispatch` 重写，键名与 `EpisodeRunState.episode_goals` 逐字相同"
        "（父子图交界按同名键传递，F1）",
    )
    task: Task | None = Field(
        default=None,
        description="刚派发的那一层目标（也是交界键 `task`）。`None` = 还没派发过",
    )

    episode_id: str | None = Field(default=None, description="本轮派发的 episode 标识")
    outcome: FromRunHarnessToEpisodeHarnessRunResp | None = Field(
        default=None, description="本轮刚收的结算（`review` 盖章的依据）"
    )

    done: bool = Field(default=False, description="run 是否结束（表末检判完 / 人喊停）")
    why: str = Field(default="", description="结束原因（全部目标收束 / 人喊停 / 无新目标）")


__all__ = ["RunState"]
