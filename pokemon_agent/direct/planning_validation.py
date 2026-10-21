"""以请求表快照验证规划操作；整版拒绝不合法输出并保留模型尝试账。"""

from collections import Counter
from collections.abc import Sequence

from pokemon_agent.brain.errors import AttemptFailed
from pokemon_agent.brain.interface import Decomposition, RunPlan
from pokemon_agent.brain.interface.domain.results import DecomposeResult, PlanResult


def pending_references(proposal: RunPlan | Decomposition, statuses: Sequence[str]) -> list[str]:
    """返回应用后合法待办引用；非法修订或不完整顺序抛 ValueError，不修改输入。"""
    changed = list(statuses)
    touched: set[int] = set()
    for update in proposal.updates:
        if update.index >= len(changed) or update.index in touched:
            raise ValueError("规划更新序号越界或重复")
        if changed[update.index] == "running":
            raise ValueError("规划不能修改 RUNNING 条目")
        touched.add(update.index)
        changed[update.index] = update.status
    expected = [f"existing:{i}" for i, status in enumerate(changed) if status == "pending"]
    expected += [f"new:{i}" for i in range(len(proposal.new_items))]
    order = proposal.execution_order
    if order is not None and (len(order) != len(expected) or set(order) != set(expected)):
        repeated = [reference for reference, count in Counter(order).items() if count > 1]
        raise ValueError(
            "execution_order 必须恰好包含全部待办引用一次；"
            f"应用 updates 后合法引用={expected}；"
            f"缺少={sorted(set(expected) - set(order))}；"
            f"非法={sorted(set(order) - set(expected))}；重复={repeated}。"
            "new:N 只能引用本次 new_items 的第 N 项；保留原顺序时可用 null。"
        )
    return expected if order is None else list(order)


def validate_result(
    result: PlanResult | DecomposeResult, statuses: Sequence[str]
) -> PlanResult | DecomposeResult:
    """成功返回原结果；上下文校验失败转成带原尝试账的 AttemptFailed。"""
    proposal = result.plan if isinstance(result, PlanResult) else result.decomposition
    try:
        pending_references(proposal, statuses)
    except ValueError as exc:
        call = result.calls[-1]
        failed = call.model_copy(
            update={
                "payload": {**call.payload, "ok": "false"},
                "error_kind": "ParseFailure",
                "error": str(exc),
            }
        )
        raise AttemptFailed(failed) from exc
    return result
