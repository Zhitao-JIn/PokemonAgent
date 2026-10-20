"""规划结构评分；空新增本身合法，语义由独立质量评分判断。"""

from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.direct.planning_validation import pending_references
from pokemon_agent.schemas.harness import FromHarnessToBrainToolDecomposeReq


def contract_checks(
    request: FromHarnessToBrainToolDecomposeReq, answer: Decomposition
) -> dict[str, bool]:
    """使用实际表快照核更新与顺序；失败不改变请求。"""
    try:
        pending_references(answer, [entry.status.value for entry in request.task_table])
        valid = True
    except ValueError:
        valid = False
    return {
        "valid_table_operations": valid,
        "new_item_limit": len(answer.new_items) <= request.max_tasks,
        "positive_budgets": all(item.budget.limit > 0 for item in answer.new_items),
        "verifiable_goals": all(
            item.goal.strip() and item.success_criteria.strip() for item in answer.new_items
        ),
    }
