"""memory：真实存储与检索，同一冻结库、两个 scorer。"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, accuracy, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.tasks.memory.schemas import MemoryDataset, MemoryRun
from evals.tasks.memory.solver import memory_solver

DATASET = Path(__file__).with_name("dataset.json")


def retrieval_metrics(ranked: list[str], relevant: list[str], k: int) -> tuple[float, float]:
    """recall@k 分母是全部相关记录，MRR 取第一条相关记录倒数。"""
    hits = set(ranked[:k]) & set(relevant)
    first = next((index for index, item in enumerate(ranked[:k], 1) if item in relevant), None)
    return len(hits) / len(set(relevant)), 1 / first if first else 0.0


@scorer(metrics=[accuracy()])
def storage_scorer() -> Scorer:
    """逐条读回全部符合才通过存储分。"""

    async def score(state: TaskState, target: Target) -> Score:
        problems = store_as(MemoryRun).storage_problems
        return Score(value="I" if problems else "C", explanation="；".join(problems))

    return score


@scorer(metrics={"recall_at_k": [mean()], "mrr": [mean()]})
def retrieval_scorer(k: int) -> Scorer:
    """查询级先算再取均值，独立于存储分。"""

    async def score(state: TaskState, target: Target) -> Score:
        dataset = MemoryDataset.model_validate(state.metadata["dataset"])
        result = store_as(MemoryRun)
        scores = [
            retrieval_metrics(result.retrieved[q.query_id], q.relevant, k) for q in dataset.queries
        ]
        return Score(
            value={
                "recall_at_k": sum(r for r, _ in scores) / len(scores),
                "mrr": sum(m for _, m in scores) / len(scores),
            },
            metadata={"ranked": result.retrieved, "k": k},
        )

    return score


@task
def memory(dataset: str = str(DATASET), k: int = 5) -> Task:
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
