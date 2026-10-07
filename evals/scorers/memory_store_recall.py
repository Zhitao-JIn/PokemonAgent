"""记忆存储与检索评分。"""

from inspect_ai.scorer import Score, Scorer, Target, accuracy, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.solvers.memory_store_recall import MemoryDataset, MemoryRun


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
