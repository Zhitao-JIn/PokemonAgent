"""导出实际跳过调用的控制账；不伪造从未构造的脑输入。"""

import json
from pathlib import Path

from pydantic import BaseModel

from pokemon_agent.schemas.harness import TraceEvent


class SkippedCall(BaseModel):
    """预算等控制原因跳过；原事件提供精确发送位置与身份。"""

    sample_id: str
    event: TraceEvent


def export_controls(batch: Path, output: Path, samples: list[str]) -> int:
    """只从原始账导出 budget_skipped；空集合也创建文件，便于区分未采集。"""
    records = []
    for sample_id in samples:
        report = json.loads((batch / "reports" / f"{sample_id}.json").read_text("utf-8"))
        work = (
            Path(report["work_directory"])
            if report.get("work_directory")
            else batch / "runs" / sample_id
        )
        for path in (work / "trace").glob("*.json"):
            event = TraceEvent.model_validate_json(path.read_text("utf-8"))
            if event.kind == "budget_skipped":
                records.append(SkippedCall(sample_id=sample_id, event=event))
    records.sort(key=lambda row: (row.sample_id, row.event.seq, row.event.uuid))
    with (output / "skipped_calls.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(record.model_dump_json() + "\n")
    (output / "skipped_calls.summary.json").write_text(
        json.dumps(
            {"count": len(records), "meaning": "控制账，不是缺失的模型响应"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(records)
