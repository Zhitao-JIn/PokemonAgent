"""运行时目标栈编辑指令：前端 → API → `RunHarness`（plan 节点消费）。

目标栈在 LangGraph 图内部流转，外部（观测台）不直接碰 `RunState`——
编辑统一走这一个指令模型，由 `RunHarness.submit_edit` 收进单槽，
`plan` 节点每轮开头消费并应用（≤ 一轮生效，不打断当前 episode）。

只有一种 kind：`push`（整栈原子替换）。`goals` 的读走现成的
`GET /runs/{id}`，不新开端点。不锁栈顶——风险（改动正在执行的栈顶）已知
且已确认接受：当前只在人工 review 阶段能编辑，时间窗内不太会跟
`plan`/`dispatch` 撞车。`apply_goals_edit` 原样整体替换 `state.goals`
（`attempts` 按 `task_id` 匹配保留，新目标记 0）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task


class FromFrontendToRunHarnessSubmitEditReq(BaseModel):
    """整栈原子替换（不锁栈顶，见模块 docstring）。

    `goals` 是完整新栈（栈顶=最后一项）；已有 `task_id` 的项保留（从而在
    `apply_goals_edit` 里保留 `attempts` 计数），新项留空由调用方生成。
    """

    kind: Literal["push"] = "push"
    goals: list[Task] = Field(
        default_factory=list,
        description="完整新目标栈（栈顶=最后一项），原子整体替换 state.goals，不受栈顶锁定",
    )
