"""scripts 测评的 task 入口：`inspect eval evals/tasks/world_actions/task.py`。

数据流：`cases.py` 的用例 → inspect Sample（用例整份进 metadata）→ `script_solver` 在真模拟器上
跑一次脚本、前后两帧进 store → `script_scorer` 判自报 / 真值两面 → `.eval` 落 `--log-dir`。
不调任何模型（`model="none"`）。`-T cases=[...]` / `-T scripts=[...]` 只跑其中一部分。
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.tasks.world_actions.cases import CASES
from evals.tasks.world_actions.schemas import ScriptCase
from evals.tasks.world_actions.scorer import script_scorer
from evals.tasks.world_actions.solver import script_solver
from evals.tasks.world_actions.takeover_samples import takeover_samples

SAMPLE_TIME_LIMIT = 300
"""单条用例的墙钟上限（秒）：最长的 heal / exit_map 真机几十秒，留足余量。"""


def to_sample(case: ScriptCase) -> Sample:
    """用例 → inspect Sample：input 是调用式，target 是期望结局码，用例整份进 metadata。"""
    call = ", ".join(f"{k}={v!r}" for k, v in case.args.items())
    return Sample(
        id=case.case_id,
        input=f"{case.script}({call})",
        target=case.expect.code,
        metadata={
            "script": case.script,
            "matrix_row": case.matrix_row,
            "case": case.model_dump(mode="json"),
        },
    )


@task
def world_actions(cases: list[str] | None = None, scripts: list[str] | None = None) -> Task:
    """scripts 测评：每条用例一次脚本调用，判自报与真值两面。

    `cases` / `scripts` 给了就只跑命中的用例（按 case_id / 脚本名过滤）。
    前置条件：给出的 id / 脚本名都在用例表里（拼错当场炸，不静默跑空集）。
    """
    dataset = [to_sample(c) for c in CASES] + takeover_samples()
    assert set(cases or []) <= {str(s.id) for s in dataset}, f"未知用例：{cases}"
    assert set(scripts or []) <= {s.metadata["script"] for s in dataset}, f"未知脚本：{scripts}"
    dataset = [s for s in dataset if cases is None or s.id in cases]
    dataset = [s for s in dataset if scripts is None or s.metadata["script"] in scripts]
    return Task(
        dataset=dataset,
        solver=script_solver(),
        scorer=script_scorer(),
        model="none",
        time_limit=SAMPLE_TIME_LIMIT,
        fail_on_error=False,
        metadata={
            "case_ids": [s.id for s in dataset],
        },
    )
