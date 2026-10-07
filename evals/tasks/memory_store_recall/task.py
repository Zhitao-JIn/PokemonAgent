"""memory：真实存储与检索，同一冻结库、两个 scorer。"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.scorers.memory_store_recall import retrieval_scorer, storage_scorer
from evals.solvers.memory_store_recall import MemoryDataset, memory_solver

DATASET = Path(__file__).resolve().parents[2] / "data" / "memory_store_recall" / "dataset.json"


@task
def memory_store_recall(dataset: str = str(DATASET), k: int = 5) -> Task:
    """装配真实 MemoryTool；数据集必须声明相关记录，k 必须为正。"""
    if k < 1:
        raise ValueError("k 必须为正")
    frozen = MemoryDataset.model_validate_json(Path(dataset).read_text(encoding="utf-8"))
    identities = {entry.record_id for entry in frozen.records}
    assert len(identities) == len(frozen.records), "record_id 不唯一"
    assert all(set(q.relevant) <= identities for q in frozen.queries), "相关性标注引用未知记录"
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
