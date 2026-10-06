"""报表：按字段、按来源、按界面桶，并排给"解码直出"与"模型读后"的准确率，再列出模型读错的帧。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .run import HEADER, RESULTS
from .schemas import FIELDS, SampleScore, ScreenHeader

REPORT = "report.md"


def build_report(report_dir: Path) -> Path:
    """读 `results.jsonl` 出 `report.md`，返回路径。纯函数，可重算。"""
    header = ScreenHeader.model_validate_json((report_dir / HEADER).read_text(encoding="utf-8"))
    scores = [
        SampleScore.model_validate_json(x)
        for x in (report_dir / RESULTS).read_text(encoding="utf-8").splitlines()
        if x
    ]
    asked = [s for s in scores if s.model_ok is not None]
    errors = sum(bool(s.model_error) for s in scores)
    tokens_in = sum(s.prompt_tokens for s in scores)
    tokens_out = sum(s.completion_tokens for s in scores)
    lines = [
        f"# 读屏测评 {header.report_id}",
        "",
        f"- 模型：{header.model or '（未调模型，只有解码直出）'}；数据集 {header.dataset_version}"
        f"（样本哈希 {header.samples_sha256[:12]}）；prompt {header.prompt_sha256[:12]}；"
        f"git {header.git_commit[:10]}{'（有改动）' if header.git_dirty else ''}",
        f"- 共 {len(scores)} 帧；模型答出 {len(asked)} 帧，出错 {errors} 帧；"
        f"输入 {tokens_in} / 输出 {tokens_out} token",
        "",
        "## 按字段",
        "",
        *_table({"全部": scores}),
        "",
        "## 按来源",
        "",
        *_table(_group(scores, lambda s: s.source)),
        "",
        "## 按界面种类（标注；v1 没标种类的按解码结果分桶）",
        "",
        *_table(_group(scores, lambda s: s.bucket)),
        "",
        "## 按类别（仅 0926 探测帧）",
        "",
        *_table(_group([s for s in scores if s.category], lambda s: s.category)),
        "",
        "## 模型读错的帧",
        "",
        *_mistakes(scores),
    ]
    path = report_dir / REPORT
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _group(scores: list[SampleScore], key: object) -> dict[str, list[SampleScore]]:
    """按键分组，组名排序。"""
    groups: dict[str, list[SampleScore]] = defaultdict(list)
    for s in scores:
        groups[key(s)].append(s)  # type: ignore[operator]
    return dict(sorted(groups.items()))


def _rate(oks: list[dict[str, bool] | None], field: str) -> str:
    """一个字段的准确率 `对/总`；没有可打分的写 —。"""
    graded = [ok[field] for ok in oks if ok is not None and field in ok]
    return f"{sum(graded)}/{len(graded)}" if graded else "—"


def _table(groups: dict[str, list[SampleScore]]) -> list[str]:
    """每组两行：解码直出、模型读后；列是字段与"全对"。"""
    head = "| 组 | 读法 | " + " | ".join(FIELDS) + " | 全对 |"
    rows = [head, "|" + "---|" * (len(FIELDS) + 3)]
    for name, group in groups.items():
        for label, oks in (
            ("解码直出", [s.decoded_ok for s in group]),
            ("模型读后", [s.model_ok for s in group]),
        ):
            if not any(ok is not None for ok in oks):
                continue
            full = [all(ok.values()) for ok in oks if ok is not None]
            cells = " | ".join(_rate(oks, f) for f in FIELDS)
            rows.append(f"| {name}（{len(group)}） | {label} | {cells} | {sum(full)}/{len(full)} |")
    return rows


def _mistakes(scores: list[SampleScore]) -> list[str]:
    """模型有字段答错（或出错）的帧，一行一帧。"""
    out = []
    for s in scores:
        if s.model_error:
            out.append(f"- `{s.sample_id}`（{s.bucket}）调用失败：{s.model_error}")
        elif s.model_ok is not None and not all(s.model_ok.values()):
            wrong = [f for f, ok in s.model_ok.items() if not ok]
            got = s.model.model_dump(include=set(wrong)) if s.model else {}
            out.append(f"- `{s.sample_id}`（{s.bucket}）错在 {', '.join(wrong)}：答 {got}")
    return out or ["（无）"]


__all__ = ["REPORT", "build_report"]
