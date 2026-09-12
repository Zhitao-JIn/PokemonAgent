"""run 级规划的解析产物：`RunPlan`（规划器的决策）与 `PlanGoal`（新目标）。

这两个是 `PlanOnceResp.plan`（`BrainTool` → `Brain`
那一跳的响应协议，见同目录）里**内嵌的计划结构**，不是独立的一跳信封：
`RunPlan` 是 `Brain.plan_once()` 从模型输出解析出的决策，`PlanGoal`
是压栈的新目标（goal / success_criteria / max_steps），**不含 task_id**
——run 级自主拆解的目标没有实验分组键（那是实验层的概念，见
`Task.task_id` 的注释）；`task_id` 由 harness 生成
（`plan-{run_id}-{序号}`）。

`events`/`goals` 都保持结构化，不在这里转文字——按项目约定，struct→text
是 `pokemon_agent.prompts.run_plan.build_prompt()` 的事（历史折成"每局一行"、
目标栈渲成带箭头的多行文本），harness（`run/plan.py::plan()`）只负责查库、
组装请求，不自己拼 prompt 字符串。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunPlan(BaseModel):
    """规划器的决策。"""

    class PlanGoal(BaseModel):
        """LLM 提出的一个新目标：具体、可判定，`task_id` 由 harness 生成。"""

        goal: str = Field(min_length=1, description="想达成什么，一句话（给大脑读）")
        success_criteria: str = Field(
            min_length=1, description="成败判据的人类可读描述（判定时用）"
        )
        max_steps: int = Field(gt=0, description="这一步最多允许跑几步")

    push_goals: list[RunPlan.PlanGoal] = Field(
        default_factory=list,
        description="压入的新目标（≤ `MAX_PLAN_PUSH` 个）；不压就留空。**LIFO：列表"
        "最后一项会变成新栈顶、最先被派发**（`run/plan.py::plan()` 原序 append，不"
        "会替模型倒转顺序）——如果要表达「先做 A 再做 B」这种递进关系，B 要排在"
        "A 前面，让 A 排在列表最后、真正先被派发",
    )
    done: bool = Field(
        default=False,
        description="是否结束整个 run（目标栈已清空 / 判断该收手）",
    )
    why: str = Field(
        default="",
        description="决策说明：done 时给结束原因，压栈时给为什么压这些",
    )
