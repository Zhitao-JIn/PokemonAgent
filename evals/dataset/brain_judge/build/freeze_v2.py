"""从 CP2 候选与请求历史裁定结果冻结 brain_judge v2。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evals.dataset.brain_judge.schemas import (
    JudgeCaseV2,
    JudgeEvidence,
    JudgeOrigin,
)

from .adjudicate_candidates import adjudicate_candidate

_ROOT = Path(__file__).resolve().parents[4]
_DRAFT = _ROOT / "eval_results" / "brain_judge" / "cp2_draft.jsonl"
_DATASET_DIR = Path(__file__).resolve().parents[1]
_V2_DIR = _DATASET_DIR / "v2"
_COVERAGE = _ROOT / "eval_results" / "brain_judge" / "cp3_coverage.md"


def _read_drafts(path: Path = _DRAFT) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def build_cases(drafts: list[dict[str, Any]]) -> list[JudgeCaseV2]:
    """Validate aligned requests and attach mechanical or history-adjudicated truth."""
    cases = []
    seen_ids: set[str] = set()
    for row in drafts:
        if not row["prompt_exact"] or not row["image_bound"]:
            raise ValueError(f"unaligned judge request: {row['candidate_id']}")
        case_id = row["event_uuid"]
        if case_id in seen_ids:
            raise ValueError(f"duplicate judge event UUID: {case_id}")
        seen_ids.add(case_id)
        request_sha256 = hashlib.sha256(
            json.dumps(row["request"], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if request_sha256 != row["request_sha256"]:
            raise ValueError(f"request hash mismatch: {row['candidate_id']}")

        if row["truth_method"] == "mechanical":
            achieved = row["achieved"]
            negative_mode = row["negative_mode"]
            truth_method = "mechanical"
            check_id = row["check_id"]
            evidence_rows = row["evidence"]
        else:
            decision = adjudicate_candidate(row)
            achieved = decision.achieved
            negative_mode = decision.negative_mode
            truth_method = "history_adjudicated"
            check_id = None
            evidence_rows = [
                {
                    "source": "request_history",
                    "locator": decision.evidence_locator,
                    "summary": decision.evidence_summary,
                }
            ]

        cases.append(
            JudgeCaseV2.model_validate(
                {
                    "case_id": case_id,
                    "request": row["request"],
                    "achieved": achieved,
                    "goal_family": row["goal_family"],
                    "negative_mode": negative_mode,
                    "truth_method": truth_method,
                    "check_id": check_id,
                    "origin": JudgeOrigin(
                        run_id=row["run_id"],
                        episode_id=row["episode_id"],
                        task_id=row["task_id"],
                        step=row["step"],
                        trace_uuid=row["event_uuid"],
                    ),
                    "request_sha256": request_sha256,
                    "evidence": [JudgeEvidence.model_validate(item) for item in evidence_rows],
                }
            )
        )
    return cases


def _coverage(cases: list[JudgeCaseV2]) -> str:
    truth = Counter((case.truth_method, case.achieved) for case in cases)
    families = Counter(case.goal_family for case in cases)
    negatives = Counter(case.negative_mode for case in cases if not case.achieved)
    runs = {case.origin.run_id for case in cases}
    episodes = {case.origin.episode_id for case in cases}
    tasks = {(case.origin.run_id, case.origin.episode_id, case.origin.task_id) for case in cases}
    lines = [
        "# brain_judge v2 CP3 覆盖报告",
        "",
        f"- 样本：{len(cases)}；唯一 run / episode / task："
        f"{len(runs)} / {len(episodes)} / {len(tasks)}",
        f"- 真值：mechanical {sum(v for (m, _), v in truth.items() if m == 'mechanical')}，"
        f"history-adjudicated "
        f"{sum(v for (m, _), v in truth.items() if m == 'history_adjudicated')} "
        f"(达成 {truth[('history_adjudicated', True)]}，"
        f"未达成 {truth[('history_adjudicated', False)]})",
        f"- 达成 / 未达成：{sum(case.achieved for case in cases)} / "
        f"{sum(not case.achieved for case in cases)}",
        "- 112 条非机械标签由专用确定性历史裁定器依据 criteria 与完整 request.history 生成；"
        "不读取 judge `done`/`why`、后续步骤或 episode 最终结果。这不是独立人工复核。",
        "- 状态目标检查整个请求历史中是否曾达成；当前数值目标检查请求时最后状态；"
        "多条件事件要求满足完整条件与先后顺序。",
        "- 1 条较早出现战斗结束文字的建议改判为达成；"
        "1 条缺少后续商店选项的建议改为未达成；"
        "20 条无建议样本均由历史证据裁定。",
        "- `case_id` 使用唯一 judge trace UUID，避免 CP2 的展示候选坐标在不同采集批次重复。",
        "- 所有 case 的请求 SHA-256 与 CP2 草稿一致；CP2 的 prompt 与图片绑定检查均为通过；"
        "1,063 条历史记录都保留 before/after 帧。",
        "- 来源限制：原批 `task_capture_20261018_102238` 无法证明采集全过程源码版本；"
        "补采 `supplement_20261018_172952` 的前后源码摘要为 `73463bb` / `898a2504`。",
        "- Inspect 指标将零分母率记为 NaN（分母 0），解释为 NA；评测报告须同时呈现分母。",
        "",
        "## goal_family",
        "",
        "| goal_family | n |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(families.items()))
    lines.extend(["", "## negative_mode", "", "| negative_mode | n |", "|---|---:|"])
    lines.extend(f"| {name} | {count} |" for name, count in sorted(negatives.items()))
    lines.append("")
    return "\n".join(lines)


def freeze_v2(
    drafts_path: Path = _DRAFT,
    dataset_dir: Path = _DATASET_DIR,
    coverage_path: Path = _COVERAGE,
) -> list[JudgeCaseV2]:
    """Create v2 files once; refuse to overwrite a frozen or existing directory."""
    output_dir = dataset_dir / "v2"
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing v2 directory: {output_dir}")
    drafts = _read_drafts(drafts_path)
    cases = build_cases(drafts)
    encoded = (
        "\n".join(
            json.dumps(case.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for case in cases
        )
        + "\n"
    )
    dataset_bytes = encoded.encode("utf-8")
    manifest = {
        "version": "v2",
        "dataset_file": "dataset.jsonl",
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
    }
    output_dir.mkdir(parents=True)
    (output_dir / "dataset.jsonl").write_bytes(dataset_bytes)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_text(_coverage(cases), encoding="utf-8")
    return cases


__all__ = ["build_cases", "freeze_v2"]
