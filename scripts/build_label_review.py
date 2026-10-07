"""把冻结截图、完整真值与诊断快照打包为可离线打开的单文件 HTML 审阅页。"""

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from evals.data.frames.schemas import FrameTruth, ScreenSample, TruthGroup
from scripts.label_cursor_evidence import CursorEvidence, cursor_evidence

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).with_name("label_review")
MATERIAL = ROOT / "eval_results/labeling_1007/full_truth"
WARNINGS: dict[str, str] = {
    "c-0419": "重绘边界：RAM 中菜单文字与光标尚未形成，候选标为 transition，请重点审核。",
    "c-0440": (
        "截图与冻结 RAM 不同步：截图显示背包，但 RAM 菜单尚未形成。"
        "当前候选按 RAM 标为 transition，请重点审核。"
    ),
    "p-option_screen": (
        "此前标了所有设置框；本次按实心光标所在框修正 options，旧 options 审核资格已撤回。"
    ),
    "p-shop_confirm": "数量框修正：旧 overlay=dialog，本次标 choice，该字段需重新审核。",
    "p-pc_withdrew": "数量框修正：旧 overlay=dialog，本次标 choice，该字段需重新审核。",
}


class Difference(BaseModel):
    """已冻结的字段差异；不是生成标注的输入。"""

    expected: Any
    actual: Any


class ReviewFrame(BaseModel):
    """离线审阅的一帧，原始样本与标注按 ID 配对。"""

    id: str
    image: str
    source: str
    note: str
    truth: FrameTruth
    tiles: list[list[int]]
    differences: dict[str, Difference] = Field(default_factory=dict)
    warning: str = ""
    cursor_evidence: CursorEvidence | None = None


class ReviewDraft(BaseModel):
    """用户审核动作；问题标记与正式字段批准不等价。"""

    status: Literal["pending", "approved", "issue"]
    note: str
    approved_groups: list[TruthGroup]
    edits: dict[TruthGroup, dict[str, Any]]
    updated_at: str


class ReviewExport(BaseModel):
    """页面导出记录的版本及逐帧审核数据。"""

    schema_version: Literal[1]
    truth_sha256: str
    samples_sha256: str
    exported_at: str
    reviews: dict[str, ReviewDraft]


class ReviewBundle(BaseModel):
    """审核导入导出的版本边界；原文件哈希防止错用其他标注快照的意见。"""

    schema_version: int = 1
    generated_at: str
    truth_sha256: str
    samples_sha256: str
    diagnostic_current: bool
    compatible_truth_sha256: list[str] = Field(default_factory=list)
    revised_groups: dict[str, list[TruthGroup]] = Field(default_factory=dict)
    imported_review: ReviewExport | None = None
    frames: list[ReviewFrame]


def digest(path: Path) -> str:
    """读取源文件指纹，不修改素材。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_tiles(sample: ScreenSample) -> list[list[int]]:
    """原始图块栏使用冻结 WRAM，而不是另一次截图的缓存。"""
    raw = zlib.decompress(base64.b64decode(sample.wram))
    if len(raw) != 8192:
        raise ValueError(f"{sample.sample_id}: 冻结 WRAM 长度错误")
    return [[raw[0x3A0 + row * 20 + column] for column in range(20)] for row in range(18)]


def imported_review(
    truth_hash: str, sample_hash: str, frames: list[ReviewFrame]
) -> ReviewExport | None:
    """只载入与当前快照一致的审核文件；版本或 ID 不匹配显式报错。"""
    path = MATERIAL / "user_review.json"
    if not path.exists():
        return None
    review = ReviewExport.model_validate_json(path.read_text("utf-8"))
    if review.truth_sha256 != truth_hash or review.samples_sha256 != sample_hash:
        raise ValueError("用户审核记录与当前快照不一致，需先核对版本")
    if not set(review.reviews) <= {frame.id for frame in frames}:
        raise ValueError("用户审核记录包含未知帧 ID")
    return review


def load_bundle() -> ReviewBundle:
    """每帧必须有对应真值；页面审阅意见独立保存，不参与评分过滤。"""
    sample_path = ROOT / "evals/data/frames/dataset/v2/samples.jsonl"
    truth_path = ROOT / "evals/data/frames/truth.jsonl"
    rows = [
        FrameTruth.model_validate_json(line) for line in truth_path.read_text("utf-8").splitlines()
    ]
    truth = {row.sample_id: row for row in rows}
    assert len(truth) == len(rows), "重复的真值 ID"
    samples = [
        ScreenSample.model_validate_json(line)
        for line in sample_path.read_text("utf-8").splitlines()
    ]
    diagnostics = json.loads((MATERIAL / "decoder_disagreements.json").read_text("utf-8"))
    differences = {row["sample_id"]: row["wrong"] for row in diagnostics}
    coverage = json.loads((MATERIAL / "coverage.json").read_text("utf-8"))
    recorded_hashes = {key.replace("\\", "/"): value for key, value in coverage["hashes"].items()}
    frames = [
        ReviewFrame(
            id=sample.sample_id,
            image=sample.frame_png,
            source=sample.source,
            note=sample.note,
            truth=truth[sample.sample_id],
            tiles=frozen_tiles(sample),
            differences=differences.get(sample.sample_id, {}),
            warning=WARNINGS.get(sample.sample_id, ""),
            cursor_evidence=cursor_evidence(sample)
            if truth[sample.sample_id].scene_truth["scene"] == "shop_items"
            else None,
        )
        for sample in samples
    ]
    assert len({frame.id for frame in frames}) == len(frames), "重复的样本 ID"
    return ReviewBundle(
        generated_at=datetime.now(UTC).isoformat(),
        truth_sha256=digest(truth_path),
        samples_sha256=digest(sample_path),
        diagnostic_current=recorded_hashes.get("evals/data/frames/truth.jsonl")
        == digest(truth_path),
        frames=frames,
        revised_groups=revised_groups(),
        imported_review=imported_review(digest(truth_path), digest(sample_path), frames),
        compatible_truth_sha256=json.loads(
            (MATERIAL / "review_compatibility.json").read_text("utf-8")
        )["compatible_truth_sha256"]
        if (MATERIAL / "review_compatibility.json").exists()
        else [],
    )


def revised_groups() -> dict[str, list[TruthGroup]]:
    """版本迁移时撤回修订组的旧通过，保留问题意见与用户编辑。"""
    path = MATERIAL / "review_fix_evidence.json"
    if not path.exists():
        return {}
    result: dict[str, list[TruthGroup]] = {}
    for row in json.loads(path.read_text("utf-8")):
        groups: list[TruthGroup] = row.get("revised_groups") or (
            ["screen_truth"] if "screen_patch" in row else ["scene_truth", "takeover_truth"]
        )
        result[row["sample_id"]] = list(dict.fromkeys(result.get(row["sample_id"], []) + groups))
    return result


def browser_script(node: str) -> str:
    """用 Node 内置 TypeScript 去类型能力生成浏览器脚本，不拉取编译依赖。"""
    source = "\n".join(
        (SOURCE / name).read_text("utf-8")
        for name in ("types.ts", "ui.ts", "compatibility.ts", "review.ts")
    )
    command = (
        "const {stripTypeScriptTypes}=require('node:module');"
        "let source='';process.stdin.setEncoding('utf8');"
        "process.stdin.on('data',part=>source+=part);"
        "process.stdin.on('end',()=>process.stdout.write(stripTypeScriptTypes(source)));"
    )
    result = subprocess.run(
        [node, "--disable-warning=ExperimentalWarning", "-e", command],
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return result.stdout


def build(output: Path, node: str) -> None:
    """单文件内嵌全部素材；JSON 的小于号转义防止内容结束 script 标签。"""
    bundle = load_bundle()
    payload = (
        bundle.model_dump_json()
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    html = (SOURCE / "page.html").read_text("utf-8")
    html = html.replace("/*__STYLE__*/", (SOURCE / "style.css").read_text("utf-8"), 1)
    html = html.replace("/*__SCRIPT__*/", browser_script(node), 1)
    html = html.replace("/*__DATA__*/", payload, 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, "utf-8")
    print(f"{output.resolve()}\n{len(bundle.frames)} frames; {output.stat().st_size:,} bytes")


def main() -> None:
    """指定 Node >=22 与输出路径；默认写审阅产物，不覆盖 truth.jsonl。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "eval_results/labeling_1007/review/decoder_truth_review.html",
    )
    args = parser.parse_args()
    if not args.node:
        parser.error("未找到 Node；请用 --node 指定支持 stripTypeScriptTypes 的 Node")
    build(args.output, args.node)


if __name__ == "__main__":
    main()
