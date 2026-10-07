"""读取统一冻结帧并挂独立真值；运行时不导入采集工具。"""

from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .schemas import FrameTruth, ScreenSample

DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v2"
TRUTH_FILE = DATASET_DIR / DEFAULT_VERSION / "truth.jsonl"
TRUTH_GROUPS: tuple[str, ...] = ("screen_truth", "takeover_truth", "terrain_truth", "scene_truth")


def load_samples(version: str = DEFAULT_VERSION) -> list[ScreenSample]:
    """读原始冻结帧；文件缺失、格式错误或重复 id 抛 DatasetError。"""
    frames = read_models(version_directory(DATASET_DIR, version) / "samples.jsonl", ScreenSample)
    if len({f.sample_id for f in frames}) != len(frames):
        raise DatasetError("samples.jsonl 有重复 sample_id")
    return frames


def load_truth(version: str = DEFAULT_VERSION) -> dict[str, FrameTruth]:
    """读该版本的唯一真值；文件缺失或重复 id 抛 DatasetError。"""
    path = (
        TRUTH_FILE
        if version == DEFAULT_VERSION
        else version_directory(DATASET_DIR, version) / "truth.jsonl"
    )
    rows = read_models(path, FrameTruth)
    if len({row.sample_id for row in rows}) != len(rows):
        raise DatasetError("truth.jsonl 有重复 sample_id")
    return {row.sample_id: row for row in rows}


def load(version: str = DEFAULT_VERSION) -> list[ScreenSample]:
    """返回已挂真值的帧；未知真值 id 或双重标注抛 DatasetError。"""
    frames, truth = load_samples(version), load_truth(version)
    unknown = set(truth) - {frame.sample_id for frame in frames}
    if unknown:
        raise DatasetError(f"真值引用未知帧：{sorted(unknown)}")
    return [_with_truth(frame, truth.get(frame.sample_id)) for frame in frames]


def _with_truth(frame: ScreenSample, extra: FrameTruth | None) -> ScreenSample:
    """同组只有一份真值；未标注字段保持原值。"""
    if extra is None:
        return frame
    update = {g: getattr(extra, g) for g in TRUTH_GROUPS if getattr(extra, g) is not None}
    clash = [g for g in update if getattr(frame, g) is not None]
    if clash:
        raise DatasetError(f"{frame.sample_id} 的 {clash} 存在双重真值")
    return frame.model_copy(update=update)
