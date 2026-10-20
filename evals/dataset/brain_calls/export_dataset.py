"""导出五类完整生产输入与独立评分依据；旧响应只保留审计文件引用。"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.common.capture_audit import KINDS
from evals.common.capture_batch import BatchReport, PackReport
from evals.paths import REPO_ROOT
from pokemon_agent.direct.trace import parse
from pokemon_agent.schemas.harness import TraceEvent

from .dataset_contract import (
    FAMILIES,
    REQUESTS,
    DatasetManifest,
    InputCase,
    ReferenceCase,
    Source,
)
from .export_controls import export_controls
from .independent_reference import (
    choose_reference,
    judge_reference,
    planning_reference,
    summary_reference,
)
from .scope_audit import verify_scope


def digest(path: Path) -> str:
    """文件字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    """结构化请求哈希，不依赖空白和换行。"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def signature(kind: str, payload: dict) -> str:
    """精确关联模型尝试的输入、原始输出及起止时刻。"""
    return canonical_digest(
        [kind, *[payload.get(key) for key in ("started_at", "ended_at", "prompt", "images", "raw")]]
    )


def load_events(work: Path) -> tuple[list, dict[str, deque]]:
    """重试各有一条账；重复输入仍用真实尝试时刻区分。"""
    raw = [
        TraceEvent.model_validate_json(path.read_text("utf-8"))
        for path in (work / "trace").glob("*.json")
    ]
    raw.sort(key=lambda event: (event.seq, event.uuid))
    lookup: dict[str, deque] = defaultdict(deque)
    for event in raw:
        if event.kind in KINDS.values():
            content = json.loads(event.content)
            lookup[signature(event.kind, content)].append(event)
    return [parse(event) for event in raw], lookup


def read_case(path: Path, work: Path, lookup: dict[str, deque]) -> InputCase:
    """完整 request 原样校验；baseline 只用于定位调用账，不参与真值生成。"""
    method, layer = path.parent.name, path.parent.parent.name
    request = REQUESTS[method].model_validate_json(path.read_text("utf-8"))
    prefix = path.name.removesuffix(".request.json")
    success, failure = (
        path.parent / f"{prefix}.{suffix}.json" for suffix in ("response", "failure")
    )
    baseline = success if success.exists() else failure if failure.exists() else None
    stored = json.loads(baseline.read_text("utf-8")) if baseline else {}
    events = []
    for call in stored.get("calls", []):
        key = signature(KINDS[method], call["payload"])
        if not lookup[key]:
            raise ValueError(f"model attempt has no matching trace: {path}")
        events.append(lookup[key].popleft())
    ending = path.parent / f"{prefix}.end.json"
    elapsed = json.loads(ending.read_text("utf-8"))["elapsed_s"] if ending.exists() else None
    meta = json.loads(events[0].meta) if events else {}
    source = Source(
        sample_id=work.name,
        request_file=path.relative_to(REPO_ROOT).as_posix(),
        request_sha256=digest(path),
        request_canonical_sha256=canonical_digest(request.model_dump(mode="json")),
        baseline_file=baseline.relative_to(REPO_ROOT).as_posix() if baseline else None,
        baseline_sha256=digest(baseline) if baseline else None,
        trace_uuids=[event.uuid for event in events],
        meta=meta,
        elapsed_s=elapsed,
        baseline_status="pending"
        if not ending.exists()
        else "success"
        if success.exists()
        else "failure",
    )
    return InputCase(
        contract_version="v2",
        case_id=f"{work.name}.{layer}.{method}.{prefix}",
        family=FAMILIES[method],
        layer=layer,
        method=method,
        request=request,
        source=source,
    )


def reference(case: InputCase, sample: object, events: list) -> ReferenceCase:
    """禁止把 baseline 对象传入独立真值函数。"""
    if case.family == "judge":
        return judge_reference(case, sample, events)
    if case.family in ("plan", "decompose"):
        return planning_reference(case, sample)
    if case.family == "choose":
        return choose_reference(case)
    return summary_reference(case)


def write_family(
    output: Path, family: str, pairs: list[tuple[InputCase, ReferenceCase]], report: PackReport
) -> DatasetManifest:
    """每族输入和评分分文件冻结，含精确生产请求 schema；独占创建。"""
    directory = output / family
    directory.mkdir(parents=True, exist_ok=False)
    for name, records in (
        ("inputs.jsonl", [pair[0] for pair in pairs]),
        ("references.jsonl", [pair[1] for pair in pairs]),
    ):
        with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(record.model_dump_json() + "\n")
    schema_paths = []
    for method in sorted({case.method for case, _ in pairs}):
        path = directory / f"{method}.request.schema.json"
        path.write_text(
            json.dumps(REQUESTS[method].model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        schema_paths.append(path)
    files = [directory / name for name in ("inputs.jsonl", "references.jsonl")] + schema_paths
    manifest = DatasetManifest(
        version="v2" if report.archive_root else "v1",
        family=family,
        cases=len(pairs),
        layers=dict(Counter(case.layer for case, _ in pairs)),
        baseline_status=dict(Counter(case.source.baseline_status for case, _ in pairs)),
        mechanical_labels=sum(ref.achieved is not None for _, ref in pairs),
        action_set_labels=sum(ref.evaluation == "action_set" for _, ref in pairs),
        rubric_cases=sum(ref.evaluation == "source_grounded_rubric" for _, ref in pairs),
        files_sha256={path.name: digest(path) for path in files},
        source_head=report.git_head,
        source_code_sha256=report.code_sha256,
        schema_hash=report.schema_hash,
        limitations=[
            "二十个短场景的现场分布，不代表独立留出集或长程能力。",
            "每例从空记忆起点恢复；过往 run 背景的覆盖取决于实际采集。",
            "仅机械标签进入混淆矩阵；source_grounded_rubric 需要独立评分器。",
            "choose 独立动作集合子集可评分；其余开放参考不冒称完备 acceptable 集合。",
            "旧响应仅为 baseline 审计材料，未用于构建期望答案。",
        ],
    )
    (directory / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def gather_cases(batch: Path, reports: list[Path], samples: dict) -> tuple[dict, dict]:
    """逐例核对来源范围与全部模型尝试，保留待核对事项。"""
    grouped = defaultdict(list)
    warnings = {}
    for report_path in reports:
        report_value = json.loads(report_path.read_text("utf-8"))
        work = (
            Path(report_value["work_directory"])
            if report_value.get("work_directory")
            else batch / "runs" / report_path.stem
        )
        events, lookup = load_events(work)
        for path in sorted((work / "brain_calls").glob("*/*/*.request.json")):
            if path.parent.name not in REQUESTS:
                continue
            case = read_case(path, work, lookup)
            limitations = verify_scope(case, events)
            if limitations:
                warnings[case.case_id] = limitations
            grouped[case.family].append((case, reference(case, samples[work.name], events)))
        for signature_key, unmatched in lookup.items():
            if unmatched and unmatched[0].kind in {
                "plan_call",
                "decompose_call",
                "choose_call",
                "judge_call",
                "summarize_task_call",
                "summarize_episode_call",
                "summarize_run_call",
            }:
                raise ValueError(f"unexported model attempts: {signature_key}")
    return grouped, warnings


def export(batch: Path, output: Path, *, partial: bool = False) -> list[DatasetManifest]:
    """完整生产输入不抽样不去重；缺原始报告或模型尝试无法对齐时失败。"""
    report = PackReport.model_validate_json((batch / "pack_report.json").read_text("utf-8"))
    samples = {sample.sample_id: sample for sample in load_samples()}
    reports = sorted((batch / "reports").glob("*.json"))
    if not partial and len(reports) != 20:
        raise ValueError(f"expected twenty completed reports; got {len(reports)}")
    if not partial:
        batch_report = BatchReport.model_validate_json(
            (batch / "batch_report.json").read_text("utf-8")
        )
        if batch_report.error or len(batch_report.completed) != 20:
            raise ValueError("batch did not finish with all audit gates passing")
    grouped, warnings = gather_cases(batch, reports, samples)
    output.mkdir(parents=True, exist_ok=False)
    manifests = [
        write_family(output, family, grouped[family], report)
        for family in ("judge", "plan", "decompose", "choose", "summary")
    ]
    (output / "scope_warnings.json").write_text(
        json.dumps(warnings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    skipped = export_controls(batch, output, [path.stem for path in reports])
    (output / "collection.json").write_text(
        json.dumps(
            {
                "batch": batch.relative_to(REPO_ROOT).as_posix(),
                "builder_sha256": {
                    path.name: digest(path) for path in sorted(Path(__file__).parent.glob("*.py"))
                },
                "completed": len(reports),
                "partial": partial,
                "skipped_calls": skipped,
                "families": [item.model_dump() for item in manifests],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifests


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    results = export(args.batch.resolve(), args.out.resolve(), partial=args.partial)
    print(json.dumps({item.family: item.cases for item in results}, ensure_ascii=True))
