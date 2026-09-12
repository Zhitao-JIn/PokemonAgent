"""`BrainTool` → `Brain` 这一跳的run 级规划请求协议：
`PlanOnceReq`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Task
from pokemon_agent.trace import TraceEvent


class PlanOnceReq(BaseModel):
    """递给规划器的上下文：run 到哪了、栈上有什么、历史发生了什么，加上这次
    问模型用的 prompt。**模块间调用只认一个输入参数**——跟 `ChooseOnceReq`
    同一个规则：这一份 req 同时是 `pokemon_agent.prompts.run_plan.build_prompt()`
    的输入（读 `prompt` 之外的字段拼出 prompt）和 `Brain.plan_once()` 的输入
    （只读 `prompt`），两边共享同一个对象。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话）")
    goals: list[Task] = Field(description="当前目标栈，栈顶 = goals[-1]（下一步要解决的）")
    events: list[TraceEvent] = Field(
        description="按 `run/plan.py` 的 `RUN_TRACE_MASK` 过滤过的 trace 事件——"
        "`build_prompt()` 从里面折出「每局一行」的历史摘要，是「根据历史压栈」"
        "的依据",
    )
    max_push: int = Field(
        description="一次最多压几个新目标（`run/plan.py` 的 `MAX_PLAN_PUSH`），"
        "prompt 里要把这个上限告诉模型",
    )
    prompt: str = Field(
        default="",
        description="这次问模型用的完整 prompt。**构造时留空**——先拿其余字段调"
        "`build_prompt(req)` 拼出字符串，再 `req.model_copy(update={'prompt': ...})`"
        "回填，才交给 `Brain.plan_once(req)`；重试时原样重问，不带纠正说明"
        "（跟 `decide_action` 的重试策略不是一回事），所以不需要 `retry_prompt()`"
        "这类方法",
    )
