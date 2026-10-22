"""按固定来源清单验收并导出完整批次，支持显式补采子集。"""

from pathlib import Path

from evals.dataset.brain_calls.export_dataset import export as export_dataset
from evals.dataset.brain_calls.source_archive import archive_sources
from evals.dataset.brain_calls.verify_dataset import verify

from .capture_batch import BatchReport, CaseReport, PackReport
from .capture_state import ControlState, save_state
from .invocation import write_record


def export(directory: Path, state: ControlState) -> None:
    """只导出固定清单的全部已审用例；不足、额外或重复用例均失败。"""
    pack = PackReport.model_validate_json((directory / "pack_report.json").read_text("utf-8"))
    reports = [
        CaseReport.model_validate_json(p.read_text("utf-8"))
        for p in sorted((directory / "reports").glob("*.json"))
    ]
    selected = set(pack.source_hashes)
    if (
        {report.sample_id for report in reports} != selected
        or len(reports) != len(selected)
        or set(state.completed) != selected
        or len(state.completed) != len(selected)
    ):
        raise RuntimeError("cannot export incomplete batch")
    batch_path = directory / "batch_report.json"
    expected = BatchReport(expected=len(selected), completed=reports)
    if batch_path.exists():
        if BatchReport.model_validate_json(batch_path.read_text("utf-8")) != expected:
            raise RuntimeError("completed batch report changed")
    else:
        write_record(batch_path, expected)
    number = state.attempts.get("export", 0) + 1
    state.attempts["export"] = number
    save_state(directory, state)
    output = directory / "exports" / f"attempt{number}" / "v2"
    export_dataset(directory, output)
    archive_sources(directory, output)
    verify(output)
    state.output = str(output)
