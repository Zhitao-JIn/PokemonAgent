"""plan 结构约束：目标数量、寻址与应用后能否继续派发。"""

from pokemon_agent.brain.interface import RunPlan
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq


def contract_checks(request: FromHarnessToBrainToolPlanOnceReq, answer: RunPlan) -> dict[str, bool]:
    """模型可放弃/重开，不能借越界更新伪造有效计划。"""
    indices = [update.index for update in answer.updates]
    valid_indices = all(index < len(request.plan) for index in indices)
    states = [str(entry.status) for entry in request.plan]
    for update in answer.updates:
        if update.index < len(states):
            states[update.index] = update.status
    return {
        "new_goal_limit": len(answer.push_goals) <= request.max_push,
        "valid_indices": valid_indices,
        "dispatchable_goal": bool(answer.push_goals) or "pending" in states,
    }
