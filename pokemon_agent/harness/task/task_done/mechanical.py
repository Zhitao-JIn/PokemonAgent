"""预算停止时只按来源章生成任务摘要，不请求校验或蒸馏模型。"""

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import TaskMemory

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def mechanical_summary(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, object]:
    """动作数与机械终止类别来自状态；质量零分表示没有模型评价。"""
    assert state.termination is not None
    reason = f"{state.task.goal}；{state.termination.value}；动作 {state.step}"
    memory = TaskMemory(
        run_id=state.run_id,
        episode_id=state.episode_id,
        entry_id=state.entry_id,
        task_id=state.task.task_id,
        goal=state.task.goal,
        steps_used=state.step,
        total_acts=state.total_acts,
        termination=state.termination.value,
        reason=reason,
        summary=reason,
        quality_score=0,
        quality_rationale="预算停止，未调用模型评价",
    )
    runtime.context.memory.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[
                FromHarnessToMemoryToolMemorizeRecord(
                    kind="task", payload=memory.model_dump(mode="json")
                ),
            ]
        )
    )
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_TASK_MEMORY,
            meta={
                "source": "mechanical_summary",
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": state.step + 1,
            },
            memory=memory,
        )
    )
    return {"reason": reason, "memory": memory}
