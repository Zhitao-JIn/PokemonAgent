"""Capture CP0 from unchanged prompt builders, offline and without input adaptation.

Run with the main checkout's .venv Python. Inputs are preserved as recorded;
current-envelope validation precedes frozen legacy validation. Legacy inputs
that cannot render directly are counted and skipped (the CP0 design ruling).
All output is staged in memory, checked for credentials/size/determinism, then
written as UTF-8 LF bytes. No production module or source dataset is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, JsonValue, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from _doubles.prompt_cases import synthetic_cases, task_summary  # noqa: E402

from evals.common.legacy_requests.registry import REQUESTS as LEGACY  # noqa: E402
from pokemon_agent.direct.prompts import (  # noqa: E402
    decide_action,
    decompose,
    judge_success,
    run_plan,
    summarize,
    summarize_run,
    summarize_task,
    verify,
)
from pokemon_agent.schemas import harness as h  # noqa: E402
from pokemon_agent.schemas.memory import ActMemory  # noqa: E402

CURRENT: dict[str, type[BaseModel]] = {
    "choose": h.FromHarnessToBrainToolChooseOnceReq,
    "judge": h.FromHarnessToBrainToolJudgeReq,
    "decompose": h.FromHarnessToBrainToolDecomposeReq,
    "plan": h.FromHarnessToBrainToolPlanOnceReq,
    "summarize": h.FromHarnessToBrainToolSummarizeReq,
    "summarize_task": h.FromHarnessToBrainToolSummarizeTaskReq,
    "summarize_run": h.FromHarnessToBrainToolSummarizeRunReq,
    "verify": h.FromHarnessToBrainToolVerifyReq,
}
TASKS: dict[str, str] = {
    "choose": "decide_action",
    "judge": "judge_success",
    "decompose": "decompose",
    "plan": "run_plan",
    "summarize": "summarize",
    "summarize_task": "summarize_task",
    "summarize_run": "summarize_run",
    "verify": "verify",
    "retry": "retry_prompt",
}
METHODS = {task: method for method, task in TASKS.items()}


class GoldenCase(BaseModel):
    """Self-contained replay input; request is the original JSON, not an upgraded copy."""

    task: str
    case_id: str
    source: Literal["history", "synthetic", "act_memory"]
    request_kind: Literal["current", "legacy", "retry"] = "current"
    request: dict[str, JsonValue]
    max_segments: int = 3
    source_ref: str = ""


class HistoricalRow(BaseModel):
    case_id: str
    method: str
    request: dict[str, JsonValue]


class TaskCounts(BaseModel):
    historical_valid: int = 0
    historical_current: int = 0
    historical_legacy: int = 0
    historical_selected: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)
    synthetic: int = 0
    act_memory: int = 0


class NondeterministicPrompt(RuntimeError):
    """A builder returned different bytes for the same serialized input."""


def parse_request(case: GoldenCase) -> BaseModel:
    method = METHODS[case.task]
    cls = LEGACY[method] if case.request_kind == "legacy" else CURRENT[method]
    return cls.model_validate(case.request)


def render_case(case: GoldenCase) -> bytes:
    """Invoke only pre-existing builders; never invoke BrainTool or a provider."""
    if case.task == "retry_prompt":
        retry = decide_action.RetryPromptReq(
            base_prompt=str(case.request["base_prompt"]),
            attempt=int(str(case.request["attempt"])),
            reason=str(case.request["reason"]),
            raw=str(case.request["raw"]),
        )
        return decide_action.retry_prompt(retry).encode("utf-8")
    req = parse_request(case)
    # Validation above selects exactly one of the pre-existing envelope types.
    # The builders also intentionally accept directly renderable frozen envelopes.
    if case.task == "decide_action":
        prompt = decide_action.build_prompt(req, max_segments=case.max_segments)
    elif case.task == "judge_success":
        prompt = judge_success.build_prompt(req)
    elif case.task == "decompose":
        prompt = decompose.build_prompt(req)
    elif case.task == "run_plan":
        prompt = run_plan.build_prompt(req)
    elif case.task == "summarize":
        prompt = summarize.build_prompt(req)
    elif case.task == "summarize_task":
        prompt = summarize_task.build_prompt(req)
    elif case.task == "summarize_run":
        prompt = summarize_run.build_prompt(req)
    elif case.task == "verify":
        prompt = verify.build_prompt(req)
    else:
        raise ValueError(f"Unknown task: {case.task}")
    return prompt.encode("utf-8")


def deterministic_prompt(case: GoldenCase) -> bytes:
    first, second = render_case(case), render_case(case)
    if first != second:
        raise NondeterministicPrompt(f"Non-deterministic prompt: {case.task}/{case.case_id}")
    return first


def evenly_spaced(items: list[GoldenCase], limit: int = 15) -> list[GoldenCase]:
    """Include endpoints; cap at 15 to keep complete inputs within the 5 MB budget."""
    if len(items) <= limit:
        return items
    return [items[i * (len(items) - 1) // (limit - 1)] for i in range(limit)]


def history_cases(counts: dict[str, TaskCounts]) -> list[GoldenCase]:
    result: list[GoldenCase] = []
    for family in ("choose", "plan", "decompose", "judge", "summary"):
        path = ROOT / "evals/dataset/brain_calls/v1" / family / "inputs.jsonl"
        rows = sorted(
            [
                HistoricalRow.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ],
            key=lambda row: row.case_id,
        )
        valid: dict[str, list[GoldenCase]] = {}
        current_valid = 0
        for row in rows:
            task = TASKS[row.method]
            count = counts[task]
            kind: Literal["current", "legacy"] = "current"
            try:
                CURRENT[row.method].model_validate(row.request)
            except ValidationError:
                old = LEGACY.get(row.method)
                if old is None:
                    raise RuntimeError(f"No validating legacy envelope: {row.case_id}") from None
                # A failure here is a stop condition, not a rendering skip.
                old.model_validate(row.request)
                kind = "legacy"
            if family == "plan":
                reason = "旧信封缺现行必填字段，不可无损升级"
                count.skipped[reason] = count.skipped.get(reason, 0) + 1
                continue
            case = GoldenCase(
                task=task,
                case_id="history-" + row.case_id,
                source="history",
                request_kind=kind,
                request=row.request,
                source_ref=path.relative_to(ROOT).as_posix() + "#" + row.case_id,
            )
            try:
                deterministic_prompt(case)
            except (AttributeError, TypeError, ValueError, AssertionError, KeyError) as error:
                if kind == "current":
                    raise
                reason = f"旧类不能直接渲染：{type(error).__name__}: {error}"
                count.skipped[reason] = count.skipped.get(reason, 0) + 1
                continue
            count.historical_valid += 1
            if kind == "current":
                count.historical_current += 1
                current_valid += 1
            else:
                count.historical_legacy += 1
            valid.setdefault(task, []).append(case)
        if family != "plan" and current_valid < 10:
            raise RuntimeError(
                f"Stop: {family} has only {current_valid} renderable current requests"
            )
        for task, cases in sorted(valid.items()):
            sampled = evenly_spaced(cases)
            counts[task].historical_selected += len(sampled)
            result.extend(sampled)
    return result


def real_cases(memory_root: Path, counts: dict[str, TaskCounts]) -> list[GoldenCase]:
    """Read twenty actual stored records, retaining their original serialized fields."""
    paths = sorted((memory_root / "step_memory").glob("*.json"))
    if len(paths) < 20:
        raise RuntimeError(f"Need 20 real ActMemory files: {memory_root / 'step_memory'}")
    result: list[GoldenCase] = []
    for path in paths[:20]:
        stored = json.loads(path.read_text(encoding="utf-8"))
        raw = stored["payload"]
        entry = ActMemory.model_validate(raw)
        for task in ("verify", "summarize_task"):
            if task == "verify":
                req = h.FromHarnessToBrainToolVerifyReq(
                    entries=[entry], goal="检查这一键的前后变化"
                )
            else:
                req = task_summary([entry])
            data = req.model_dump(mode="json", round_trip=True)
            data["entries"] = [raw]
            result.append(
                GoldenCase(
                    task=task,
                    case_id="act-" + path.stem,
                    source="act_memory",
                    request=data,
                    source_ref=path.resolve().as_posix(),
                )
            )
            counts[task].act_memory += 1
    return result


def secret_scan(data: bytes, label: str) -> Counter[str]:
    """Search broad markers, reject credential-shaped values without printing secrets.

    Ordinary prompt words (e.g. keyboard or token budget) are reviewed separately
    from credential assignments. Errors reveal only the affected artifact name.
    """
    text = data.decode("utf-8")
    markers = Counter(
        match.group(0).lower()
        for match in re.finditer(r"key|token|authorization|secret|password", text, re.I)
    )
    credentials = (
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|authorization|secret|password)\b[\s\"']*[:=][\s\"']*[^\s\"',}\]]+",
        r"\bsk-[A-Za-z0-9_-]{16,}",
        r"(?i)\bBearer\s+[A-Za-z0-9._~-]{10,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    )
    if any(re.search(pattern, text) for pattern in credentials):
        raise RuntimeError(f"Credential-like content; refusing to write {label}")
    return markers


def capture(memory_root: Path, output: Path) -> None:
    counts = {task: TaskCounts() for task in TASKS.values()}
    cases = history_cases(counts)
    for task, name, request in synthetic_cases():
        cases.append(
            GoldenCase(
                task=task,
                case_id=name,
                source="synthetic",
                request_kind="retry" if task == "retry_prompt" else "current",
                request=request,
            )
        )
        counts[task].synthetic += 1
    cases.extend(real_cases(memory_root, counts))
    pending: dict[Path, bytes] = {}
    markers: Counter[str] = Counter()
    for case in sorted(cases, key=lambda c: (c.task, c.case_id)):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", case.case_id):
            raise ValueError(f"Unsafe case id: {case.case_id}")
        stem = Path(case.task) / case.case_id
        prompt = deterministic_prompt(case)
        request = (case.model_dump_json(indent=2) + "\n").encode("utf-8")
        for suffix, data in ((".req.json", request), (".prompt.txt", prompt)):
            relative = Path(str(stem) + suffix)
            if relative in pending:
                raise ValueError(f"Duplicate case: {relative}")
            if b"\r" in data:
                raise ValueError(f"Non-LF content: {relative}")
            markers.update(secret_scan(data, str(relative)))
            pending[relative] = data
    size = sum(map(len, pending.values()))
    if size > 5_000_000:
        raise RuntimeError(f"Golden size {size} exceeds 5 MB")
    # Never silently remove artifacts. A changed input inventory requires review.
    existing = {p.relative_to(output) for p in output.rglob("*") if p.is_file()}
    stale = existing - pending.keys()
    if stale:
        raise RuntimeError(f"Unexpected existing artifacts: {sorted(map(str, stale))}")
    digest = hashlib.sha256()
    for relative, data in sorted(pending.items()):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest.update(relative.as_posix().encode("utf-8") + b"\0" + data)
    print(
        json.dumps(
            {
                "tasks": {task: count.model_dump() for task, count in sorted(counts.items())},
                "cases": len(cases),
                "files": len(pending),
                "bytes": size,
                "sha256": digest.hexdigest(),
                "secret_markers": dict(markers),
                "credential_matches": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-root", type=Path, default=ROOT.parents[1] / "memory")
    args = parser.parse_args()
    capture(args.memory_root, ROOT / "tests/prompt/golden")


if __name__ == "__main__":
    main()
