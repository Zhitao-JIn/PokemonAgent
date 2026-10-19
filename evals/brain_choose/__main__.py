"""离线单步决策入口：显式运行才装配 chooser，提供者失败的现场不进分母。"""

import argparse
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from evals.common.run import run_evaluation
from evals.dataset.brain_choose import ChooseCase, load
from evals.runconfig import load_config
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.direct.interface import ChoosePort

from .cases import build_cases
from .scorer import build_metrics
from .solver import ChooseRun, ProviderUnreachable, choose_case


def select_cases(
    cases: Sequence[ChooseCase], case_ids: list[str], scenes: list[str], tags: list[str]
) -> list[ChooseCase]:
    """同类选择取并集、不同条件取交集；未知值或空结果抛 ValueError。"""
    for label, wanted, known in (
        ("case", set(case_ids), {case.case_id for case in cases}),
        ("scene", set(scenes), {str(case.scene) for case in cases}),
        ("tag", set(tags), {tag for case in cases for tag in case.tags}),
    ):
        if unknown := wanted - known:
            raise ValueError(f"未知 {label}：{sorted(unknown)}")
    selected = [
        case
        for case in cases
        if (not case_ids or case.case_id in case_ids)
        and (not scenes or str(case.scene) in scenes)
        and (not tags or set(case.tags).intersection(tags))
    ]
    if not selected:
        raise ValueError("没有符合筛选条件的用例")
    return selected


def run_cases(
    cases: Sequence[ChooseCase], chooser: ChoosePort, workers: int
) -> tuple[list[ChooseCase], list[ChooseRun], list[tuple[str, str]]]:
    """线程池运行；恢复输入顺序，排除 ProviderUnreachable，其余异常原样上抛。"""
    assert workers > 0, "run_cases requires positive workers"
    runs: dict[str, ChooseRun] = {}
    unavailable: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(choose_case, case, chooser): case.case_id for case in cases}
        for future in as_completed(futures):
            case_id = futures[future]
            try:
                runs[case_id] = future.result()
            except ProviderUnreachable as error:
                unavailable[case_id] = str(error)
    scored = [case for case in cases if case.case_id in runs]
    skipped = [
        (case.case_id, unavailable[case.case_id]) for case in cases if case.case_id in unavailable
    ]
    return scored, [runs[case.case_id] for case in scored], skipped


def main(argv: list[str] | None = None) -> int:
    """校验筛选后才装配生产 chooser；有评分失败返回 1，不通样本打印但不计分。"""
    parser = argparse.ArgumentParser(description="brain choose 单步离线评测")
    parser.add_argument("--text-model")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.workers <= 0:
        parser.error("--workers 必须为正整数")
    cases = load(args.version)
    try:
        selected = select_cases(cases, args.case, args.scene, args.tag)
    except ValueError as error:
        parser.error(str(error))
    model = args.text_model
    if model is None:
        models = load_config()["models"]
        if not models.get("text_model"):
            raise ValueError("config.json models 缺少 text_model")
        model = str(models["text_model"])
    chooser = BrainTool.build(text=model).chooser
    scored, runs, skipped = run_cases(selected, chooser, args.workers)
    status = (
        run_evaluation(
            test_cases=build_cases(scored, runs),
            metrics=build_metrics(selected),
            results_folder="eval_results/brain_choose",
            hyperparameters={"dataset": args.version, "cases": len(scored), "text_model": model},
        )
        if scored
        else 0
    )
    for case_id, reason in skipped:
        print(f"不进分母：{case_id}：{reason}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
