"""`FromHarnessToBrainToolPlanOnceReq`：harness → `BrainTool` 的 run 级规划请求。

**只装素材**（目标栈、事件）——`BrainTool` 自己拼 prompt（`prompts.run_plan`
的 `build_prompt()`，与 `plan()` 里渲染 `goal_stack`/`history` 共用同一份渲染
函数），再交给大脑。harness 不碰 prompt（0913 定案）。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.brain.interface import Task
from pokemon_agent.trace import TraceEvent


class FromHarnessToBrainToolPlanOnceReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的规划请求。

    run_id：这次 run 的标识（trace 记账用，大脑不需要）。
    goals：当前目标栈，栈顶 = `goals[-1]`。
    events：按 `run/nodes/plan.py` 的 `RUN_TRACE_MASK` 过滤过的 trace 事件——
        `build_prompt()` 从里面折出「每局一行」的历史摘要，是「根据历史压栈」
        的依据。
    max_push：一次最多压几个新目标（`run/nodes/plan.py` 的 `MAX_PLAN_PUSH`），
        prompt 里要把这个上限告诉模型。

    **`prompt` 不是本模型的字段**（0913 删）：`BrainTool.plan()` 入口处调
    `build_prompt(req)` 拼它，只活在那一次调用的局部。
    """

    run_id: str
    goals: list[Task]
    events: list[TraceEvent]
    max_push: int
