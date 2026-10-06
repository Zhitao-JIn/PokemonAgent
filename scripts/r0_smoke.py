"""R0 冒烟（plan2）：用真 inspect-ai 库跑一条最小 @task，验证 API 形状与 spec2 假设。

不进 evals/、不碰被测系统——solver 是假的（不调模型，mockllm 兜底），产物落
`eval_results/r0/logs/`。跑法：`uv run python scripts/r0_smoke.py`（或 .venv python）。

核对清单（对应 spec2 §一/§六 的假设）：
1. @task 装配 Task(dataset, solver, scorer) 真签名；
2. eval_set(tasks, log_dir, epochs=…) 真签名与返回 (bool, list[EvalLog])；
3. epochs + epochs_reducer=pass_at(k) 的 pass@k 走法；
4. accuracy()/stderr() 直接出指标；
5. .eval 日志落盘，metrics 进 EvalLog.results。
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Epochs, Task, eval_set, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig  # noqa: F401 —— 确认 GenerateConfig 可导入
from inspect_ai.scorer import (
    CORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    pass_at,
    scorer,
    stderr,
)
from inspect_ai.solver import Generate, TaskState, solver

LOG_DIR = Path(__file__).resolve().parent.parent / "eval_results" / "r0" / "logs"


@solver
def fixed_answer() -> ...:  # type: ignore[no-any-unimported]
    """假 solver：不调模型，固定作答——R0 只验装配与打分链路。"""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.output.completion = "42"
        return state

    return solve


@scorer(metrics=[accuracy(), stderr()])
def exact_42() -> Scorer:
    """真值 42 的精确匹配 scorer（inspect 的 Score：value 用 CORRECT/INCORRECT 字面量）。"""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(
            value=CORRECT if state.output.completion == target.text else "I",
            answer=state.output.completion,
            explanation="R0 冒烟：固定作答比对",
        )

    return score


@task
def r0_smoke() -> Task:
    """最小任务：2 样本 × epochs=2，全答对。"""
    return Task(
        dataset=[Sample(input="q1", target="42"), Sample(input="q2", target="42")],
        solver=fixed_answer(),
        scorer=exact_42(),
    )


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ok, logs = eval_set(
        r0_smoke(),
        log_dir=str(LOG_DIR),
        model="mockllm/model",
        epochs=Epochs(2, reducer=pass_at(2)),
        display="none",
    )
    assert ok, "eval_set 未成功收尾"
    log = logs[0]
    assert log.results is not None and log.results.scores, "没有打分结果"
    metrics = {name: m.value for s in log.results.scores for name, m in s.metrics.items()}
    eval_files = sorted(p.name for p in LOG_DIR.glob("*.eval"))
    print("scorer:", list(log.results.scores)[0].name)
    print("metrics:", metrics)
    print("samples:", log.results.total_samples, "eval files:", eval_files)
    print("R0 冒烟通过")


if __name__ == "__main__":
    main()
