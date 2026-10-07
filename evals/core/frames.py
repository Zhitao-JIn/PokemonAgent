"""帧测评（decode / vision_perceive）共用的冻结数据集；加载不推进模拟器、不现场生成真值。"""

from evals.data.frames.build import load_samples
from evals.data.frames.schemas import FrameTruth, ScreenSample
from evals.data.frames.truth import TRUTH_GROUPS, load_truth


def load_frames(version: str = "v2") -> list[ScreenSample]:
    """读取统一帧集，再挂上唯一真值文件；没有标某组的帧保持 None。

    前置条件：同一帧的同一组真值只有一个来源（帧文件或 truth.jsonl）。
    """
    frames = load_samples(version)
    truth = load_truth()
    return [_with_truth(frame, truth.get(frame.sample_id)) for frame in frames]


def _with_truth(frame: ScreenSample, extra: FrameTruth | None) -> ScreenSample:
    """把一行补充真值的各组挂到帧上；同组两处都有真值当场炸。"""
    if extra is None:
        return frame
    update = {g: getattr(extra, g) for g in TRUTH_GROUPS if getattr(extra, g) is not None}
    clash = [g for g in update if getattr(frame, g) is not None]
    assert not clash, f"{frame.sample_id} 的 {clash} 在帧文件与 truth.jsonl 里都有"
    return frame.model_copy(update=update)
