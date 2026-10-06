"""bridge —— 项目 ↔ inspect 翻译层（spec2 §二）。

v1 落两件事：
1. `EvalSample`（`evals/schema/sample.py`）→ inspect `Sample` 的字段翻译（R3）；
2. run_id 命名（`run_id_for`，re-export 自 runner/one——eval/`#e<n>` 后缀的唯一真源）。

RunResult → sample metadata 的翻译在 solver 内就地完成（产物落盘后 scorer 从
metadata 拿 run_id 定位 trace），不另设搬运层。
"""

from __future__ import annotations

from inspect_ai.dataset import Sample

from evals.data import REPO_ROOT  # noqa: F401 —— run-one 断言的仓库根
from evals.e2e.runner.one import run_id_for
from evals.schema import EvalSample

__all__ = ["run_id_for", "sample_to_inspect", "samples_to_dataset"]


def sample_to_inspect(sample: EvalSample) -> Sample:
    """`EvalSample` → inspect `Sample`：prompt = goal，target = success_criteria。

    决策要用到的样本身份全部进 metadata（View 钻取 + Langfuse 定位的接线点）。
    """
    return Sample(
        input=sample.goal,
        target=sample.success_criteria,
        id=sample.sample_id,
        metadata={
            "sample_id": sample.sample_id,
            "dataset_version": sample.dataset_version,
            "category": sample.category,
            "max_steps": sample.max_steps,
            "check_id": sample.check_id or "",
        },
    )


def samples_to_dataset(samples: list[EvalSample]) -> list[Sample]:
    """样本表 → inspect 数据集（保序）。"""
    return [sample_to_inspect(s) for s in samples]
