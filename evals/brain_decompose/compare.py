"""decompose 结构约束；任务必要性和先后依赖另由证据量表评分。"""

from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.schemas.harness import FromHarnessToBrainToolDecomposeReq


def contract_checks(
    request: FromHarnessToBrainToolDecomposeReq, answer: Decomposition
) -> dict[str, bool]:
    """以当前请求的上限衡量，不用全局常量替代现场预算。"""
    return {
        "nonempty_tasks": bool(answer.tasks),
        "task_limit": len(answer.tasks) <= request.max_tasks,
        "positive_budgets": all(task.max_steps > 0 for task in answer.tasks),
        "verifiable_goals": all(
            task.goal.strip() and task.success_criteria.strip() for task in answer.tasks
        ),
    }
