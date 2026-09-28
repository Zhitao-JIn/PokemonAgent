"""核对页：一次读屏测评的逐帧对照，样式同 observation_check。

每帧：截图 / 喂给模型的观测 / 标注 · 解码直出 · 模型读后三列对照。

纯函数，读 `header.json` + `results.jsonl` + 数据集，写 `review.html`；可反复重算。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .build import load_samples
from .observe import observation_text, screen_text, task_facts
from .report import REPORT
from .run import HEADER, RESULTS
from .schemas import FIELDS, NORMAL_SCENES, TAKEOVER_SCENES, SampleScore, ScreenHeader, ScreenLabel

REVIEW = "review.html"
TEMPLATE = Path(__file__).with_name("review_template.html")


def build_review(report_dir: Path) -> Path:
    """出 `review.html`，返回路径。"""
    header = ScreenHeader.model_validate_json((report_dir / HEADER).read_text(encoding="utf-8"))
    samples = {s.sample_id: s for s in load_samples(header.dataset_version)}
    scores = [
        SampleScore.model_validate_json(x)
        for x in (report_dir / RESULTS).read_text(encoding="utf-8").splitlines()
        if x
    ]
    records = []
    for n, score in enumerate(scores, start=1):
        sample = samples[score.sample_id]
        observation = observation_text(task_facts(screen_text(sample)))
        status = _status(score)
        records.append(
            {
                "seq": n,
                "id": score.sample_id,
                "cat": score.bucket,
                "source": score.source,
                "label_scene": sample.label.scene,
                "label_at_start": sample.label.at_start,
                "status": status,
                "tag": _TAGS[status],
                "frame": sample.frame_png,
                "ram": '<h3>喂给模型的观测（task 层看到的）</h3><pre class="grid">'
                + html.escape(observation)
                + "</pre>",
                "cmp": _compare(sample.label, score)
                + (f'<p class="note">说明：{html.escape(sample.note)}</p>' if sample.note else "")
                + (
                    '<p class="note" style="color:#c62828">模型调用失败：'
                    + html.escape(score.model_error)
                    + "</p>"
                    if score.model_error
                    else ""
                ),
            }
        )
    report_md = report_dir / REPORT
    report = report_md.read_text(encoding="utf-8") if report_md.is_file() else ""
    summary = (
        '<div class="sumbox"><h4>报表原文（report.md）</h4>'
        '<pre style="white-space:pre-wrap;font-size:12px">' + html.escape(report) + "</pre></div>"
    )
    scenes = [*NORMAL_SCENES, *TAKEOVER_SCENES]
    payload = json.dumps(
        {"records": records, "summary": summary, "scenes": scenes}, ensure_ascii=False
    )
    payload = payload.replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__DATA_JSON__", payload)
    page = page.replace("<title>解码核对</title>", f"<title>读屏测评 {header.report_id}</title>")
    path = report_dir / REVIEW
    path.write_text(page, encoding="utf-8")
    return path


_TAGS = {
    "both_ok": "✅",
    "model_fixed": "🟢 模型补对",
    "model_broke": "🔴 模型改错",
    "both_wrong": "❌ 都错",
}
"""每帧的四种状态：两种读法各自全对与否。"""


def _status(score: SampleScore) -> str:
    """按"解码直出全对 / 模型读后全对"分四类；没问模型时按解码算。"""
    dec = all(score.decoded_ok.values())
    mod = all(score.model_ok.values()) if score.model_ok is not None else dec
    if dec and mod:
        return "both_ok"
    if mod:
        return "model_fixed"
    if dec:
        return "model_broke"
    return "both_wrong"


def _compare(label: ScreenLabel, score: SampleScore) -> str:
    """逐字段三列：标注 / 解码直出 / 模型读后，对的绿、错的红。"""
    rows = []
    for field in FIELDS:
        if field == "quantity" and label.quantity is None:
            continue
        if field == "at_start" and label.at_start is None and score.decoded.at_start is None:
            continue
        cells = [f"<th>{field}</th><td>{_fmt(getattr(label, field))}</td>"]
        for answer, oks in ((score.decoded, score.decoded_ok), (score.model, score.model_ok)):
            if answer is None or oks is None:
                cells.append('<td class="empty">—</td>')
                continue
            ok = oks.get(field, True)
            color = "#1a7f37" if ok else "#c62828;background:#fff5f5"
            cells.append(f'<td style="color:{color}">{_fmt(getattr(answer, field))}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="fields compare-table"><tr><th>字段</th><th>标注</th><th>解码直出</th>'
        "<th>模型读后</th></tr>" + "".join(rows) + "</table>"
    )


def _fmt(value: object) -> str:
    """一个字段值 → 表格里的文字。"""
    if isinstance(value, list):
        text = " / ".join(value) if value else "（无）"
    elif value is None or value == "":
        text = "（空）"
    else:
        text = str(value)
    return html.escape(text)


__all__ = ["REVIEW", "build_review"]
