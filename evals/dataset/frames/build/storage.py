"""统一帧集的采集写入：按来源替换样本，独立期望只存 truth.jsonl。"""

from collections.abc import Sequence
from pathlib import Path

from ..loader import TRUTH_GROUPS, load_truth
from ..schemas import FrameTruth, ScreenSample

DATASET_DIR = Path(__file__).resolve().parents[1]


def save_frames(
    frames: Sequence[ScreenSample], *, version: str = "v2", replace_sources: Sequence[str]
) -> Path:
    """替换指定采集来源，保留其余来源；将随帧提供的独立期望移入唯一真值文件。

    前置条件：输入ID唯一且来源都在replace_sources中。独立期望直接保存；
    文件读写失败原样上抛。返回统一samples.jsonl路径。
    """
    assert len({frame.sample_id for frame in frames}) == len(frames)
    assert all(frame.source in replace_sources for frame in frames)
    path = DATASET_DIR / version / "samples.jsonl"
    old = (
        [ScreenSample.model_validate_json(line) for line in path.read_text("utf-8").splitlines()]
        if path.exists()
        else []
    )
    truth_file = DATASET_DIR / version / "truth.jsonl"
    truth = load_truth(version) if truth_file.is_file() else {}
    kept = [frame for frame in old if frame.source not in replace_sources]
    for frame in frames:
        _save_expectations(frame, truth)
    merged = kept + [frame.model_copy(update=dict.fromkeys(TRUTH_GROUPS)) for frame in frames]
    assert len({frame.sample_id for frame in merged}) == len(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(frame.model_dump_json() + "\n" for frame in merged), "utf-8")
    truth_file.write_text("".join(row.model_dump_json() + "\n" for row in truth.values()), "utf-8")
    return path


def _save_expectations(frame: ScreenSample, truth: dict[str, FrameTruth]) -> None:
    """独立期望与旧行合并，不触碰输入未提供的字段组。"""
    groups = {group: getattr(frame, group) for group in TRUTH_GROUPS if getattr(frame, group)}
    if frame.label_checked and "screen_truth" not in groups:
        groups["screen_truth"] = frame.label.model_dump(
            include={"overlay", "dialog_text", "options", "cursor"}
        )
    if not groups:
        return
    row = truth.get(frame.sample_id) or FrameTruth(
        sample_id=frame.sample_id, labeler="capture_expectation", note=frame.note
    )
    truth[frame.sample_id] = row.model_copy(update=groups)
