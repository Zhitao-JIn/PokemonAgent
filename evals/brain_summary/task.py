"""brain_summary：81 次冻结生产蒸馏，契约和模型审阅分层汇总。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.brain_summary.contract import Layer
from evals.brain_summary.dataset import DEFAULT_VERSION, load
from evals.brain_summary.scorer import contract_scorer, quality_scorer
from evals.brain_summary.solver import summary_solver
from evals.runconfig import load_config, resolve_grader
from pokemon_agent.env import load_env_file


@task
def brain_summary(
    version: str = DEFAULT_VERSION,
    model: str | None = None,
    grader_model: str | None = None,
    layer: Layer | None = None,
) -> Task:
    """默认评三层；单层筛选只报该层，三层宏平均保留未知。"""
    load_env_file()
    configuration = load_config()
    model = model or str(configuration["models"]["summary_model"])
    grader = resolve_grader(configuration["evaluation_models"], grader_model)
    cases = [case for case in load(version) if layer is None or case.layer == layer]
    if not cases:
        raise ValueError("summary layer selection is empty")
    return Task(
        dataset=[
            Sample(
                id=case.case_id,
                input=f"{case.layer} summary",
                metadata={"case": case.model_dump(mode="json")},
            )
            for case in cases
        ],
        solver=summary_solver(model),
        scorer=[contract_scorer(), quality_scorer(grader)],
        model="none",
        fail_on_error=False,
        metadata={
            "capability": "summary",
            "dataset_version": version,
            "tested_model": model,
            "grader_model": grader.model if grader is not None else "none",
            "layer": layer or "all",
        },
    )
