"""批次发布前自动审计：调用、等待与新规划分支覆盖分开报告。"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .capture_audit import audit_capture
from .capture_batch import CaseReport
from .capture_review import ReviewWaitAudit, audit_review
from .invocation import write_record


class BatchAudit(BaseModel):
    """覆盖表示实际观察到的路径，不把缺少路径伪报成通过。"""

    completed: int
    ports: dict[str, int] = Field(default_factory=dict)
    port_elapsed_s: float = 0
    model_elapsed_s: float = 0
    reviews: dict[str, ReviewWaitAudit] = Field(default_factory=dict)
    branches: dict[str, int] = Field(default_factory=dict)
    coverage_gaps: list[str] = Field(default_factory=list)


def branch_counts(work: Path) -> dict[str, int]:
    """仅读现场及候选统计路径；不产生评分标签。"""
    counts = {name: 0 for name in ("empty_planning", "pending_revised", "reopened", "blocked")}
    for response in (work / "brain_calls").glob("*/*/*.response.json"):
        method = response.parent.name
        value = json.loads(response.read_text("utf-8"))
        if method == "judge":
            counts["blocked"] += value.get("decision") == "blocked"
        if method not in ("plan", "decompose"):
            continue
        proposal = value["plan" if method == "plan" else "decomposition"]
        request_path = response.with_name(response.name.replace(".response.json", ".request.json"))
        request = json.loads(request_path.read_text("utf-8"))
        table = request["plan" if method == "plan" else "task_table"]
        counts["empty_planning"] += not proposal["new_items"]
        for change in proposal["updates"]:
            row = table[change["index"]]
            counts["pending_revised"] += row["status"] == "pending"
            counts["reopened"] += change["status"] == "pending" and row["status"] != "pending"
    return counts


def audit_batch(directory: Path) -> BatchAudit:
    """二十例全部有结算、录制闭合且双向对账后才允许导出。"""
    reports = list((directory / "reports").glob("*.json"))
    if len(reports) != 20:
        raise ValueError("batch audit requires twenty reports")
    summary = BatchAudit(completed=20)
    for path in reports:
        report = CaseReport.model_validate_json(path.read_text("utf-8"))
        work = Path(report.work_directory)
        calls, waits = audit_capture(work), audit_review(work)
        if report.exit_code or report.error or report.run_result is None or calls != report.audit:
            raise ValueError(f"case evidence changed: {report.sample_id}")
        if (
            calls.missing_from_recording
            or calls.missing_from_trace
            or any(p.pending for p in calls.ports.values())
        ):
            raise ValueError(f"case calls incomplete: {report.sample_id}")
        if waits.pending or waits.failed or waits.missing:
            raise ValueError(f"case review waits incomplete: {report.sample_id}")
        summary.reviews[report.sample_id] = waits
        for port, coverage in calls.ports.items():
            summary.ports[port] = summary.ports.get(port, 0) + coverage.requests
            summary.port_elapsed_s += coverage.elapsed_s
            summary.model_elapsed_s += coverage.model_elapsed_s
        for branch, count in branch_counts(work).items():
            summary.branches[branch] = summary.branches.get(branch, 0) + count
    summary.coverage_gaps = [branch for branch, count in summary.branches.items() if not count]
    target = directory / "coverage_report.json"
    if not target.exists():
        write_record(target, summary)
    elif BatchAudit.model_validate_json(target.read_text("utf-8")) != summary:
        raise ValueError("batch coverage report changed")
    return summary
