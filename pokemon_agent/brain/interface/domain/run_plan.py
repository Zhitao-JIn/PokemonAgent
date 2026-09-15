"""run 级规划的解析产物：`RunPlan`（规划器的决策）。

`RunPlan` 是 `PlanOnceResp.plan`（`BrainTool` → harness 那一跳的响应协议）里
**内嵌的计划结构**，不是独立的一跳信封：它是 `Brain.plan()` 从模型输出解析出的
决策，三部分——`push_goals`（新目标）、`updates`（对目标表已有条目的状态表态）、
`done`/`why`（收手判定与理由）。

**目标用"表内序号"寻址，不用 `task_id`**（0914 S2）：`updates` 要指向"表里哪一行"，
而 prompt 里给模型看的就是 `[0]`/`[1]` 这种序号（`goals_lines` 渲染的第一列）。
让 brain 去认 `task_id` 是把 run 级的标识符泄进第三方模块——序号是"位置"，
`task_id` 是"身份"，位置由调用方翻译（`harness/brain_planner.py` 做这个映射）。

**LIFO 的说明已删**（0914 S2）：目标表是**从上往下**做的，表序 = 派发顺序。
旧文档里"最先做的要排在列表最后"那段是旧栈语义的产物，已随栈一起退役。

`plan` 的素材（目标表、局索引、详情、地图事实）都保持结构化，不在这里转文字——
按项目约定，struct→text 是 `pokemon_agent.tools.prompts.run_plan.build_prompt()`
的事，harness（`run/nodes/plan.py::plan()`）只负责取记忆、组装请求，不自己拼
prompt 字符串。
"""

from __future__ import annotations

from typing import Literal

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

    class PlanUpdate(BaseModel):
        """LLM 对**目标表里已有的一条**表态：重开它，或者放弃它。

        `index` 是表内序号（prompt 里 `[ ]` 里那个），**越界由调用方丢弃**——
        模型数错行不是异常，只是这条表态作废。

        `status` 只允许两个值，因为余下的状态是**机械事实**：`completed`/`failed`
        由 harness 从这一局的结算推导（R2：必须为真的判断走机械来源，不走 LLM 叙述），
        模型无权书写。这两个值对应的是**主观决策**——"我想再试一次"（`pending`）
        与"我不打算做了"（`abandoned`）。
        """

        index: int = Field(ge=0, description="目标表里的序号（从 0 起，prompt 里方括号那个）")
        status: Literal["pending", "abandoned"] = Field(
            description="改成什么状态：`pending` = 重开（再派一局试试），"
            "`abandoned` = 放弃（不做了）"
        )
        note: str = Field(default="", description="为什么（会留在目标表里当教训）")

    push_goals: list[PlanGoal] = Field(
        default_factory=list,
        description="追加的新目标（不压就留空）。**按先后顺序排列**——第一条最先被派发，"
        "与你写下的顺序一致（目标表从上往下做，不需要倒着排）",
    )
    updates: list[PlanUpdate] = Field(
        default_factory=list,
        description="对目标表已有条目的表态（重开 / 放弃）。表上没被点名的条目原样不动",
    )
    done: bool = Field(
        default=False,
        description="是否结束整个 run（没有待做的目标、或判断该收手了）",
    )
    why: str = Field(
        default="",
        description="决策说明：done 时给结束原因，其余给为什么这么规划",
    )
