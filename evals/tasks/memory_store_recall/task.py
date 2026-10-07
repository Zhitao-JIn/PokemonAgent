"""memory：真实存储与检索，同一冻结库、两个 scorer。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.dataset.memory_store_recall import load
from evals.scorers.memory_store_recall import retrieval_scorer, storage_scorer
from evals.solvers.memory_store_recall import memory_solver


@task
def memory_store_recall(version: str = "v1", k: int = 5) -> Task:
    """装配真实 MemoryTool；数据集必须声明相关记录，k 必须为正。"""
    if k < 1:
        raise ValueError("k 必须为正")
    [frozen] = load(version)
    return Task(
        dataset=[
            Sample(
                id="frozen_memory",
                input="冻结库写入、读回与检索",
                metadata={"dataset": frozen.model_dump(mode="json")},
            )
        ],
        solver=memory_solver(k),
        scorer=[storage_scorer(), retrieval_scorer(k)],
        model="none",
        fail_on_error=False,
    )
