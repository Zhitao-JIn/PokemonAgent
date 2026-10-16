"""交给 harness 跑的任务契约。

**跨层**：也出现在 `WorldPort.reset()` / `GameToolPort.reset()` 的签名里。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Task(BaseModel):
    """一个有明确成败判据的任务。**episode 的边界就是任务的边界。**

    为什么不用"通关"做 episode：通关是几千步、只产出一个 0/1 结果，
    机制三的蒙特卡洛回填折扣一路乘下去，回填到前期步骤上几乎是噪声；
    评测也只能报"通关了没有"这一个二值数字。任务级则能报成功率、失败模式分布、
    有记忆 vs 无记忆的对比。

    但任务有**下界**：必须长到单靠上下文装不下、必须跨任务复用经验才做得好，
    否则记忆架构就失去了存在理由。"打赢二号道馆"合适，"和 NPC 说句话"不合适。
    """

    task_id: str = Field(description="任务标识，同一任务的多次尝试共用它")
    goal: str = Field(description="给 LLM 读的目标描述，会进 prompt")
    success_criteria: str = Field(description="成败判据的人类可读描述；判定由 world 实现")
    max_steps: int = Field(
        description="本层预算，> 0。**单位随所在层**：作 episode 目标时是 task 数，作 task 时是键数"
    )
    initial_state_hint: str = Field(
        default="",
        description="实验采集起点要求；不参与模型 prompt，仅用于选择和核对 state 文件",
    )
