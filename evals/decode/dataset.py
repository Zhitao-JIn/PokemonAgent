"""独立真值与冻结帧组成一帧一个 DeepEval 用例。"""

import json
from collections.abc import Sequence

from deepeval.test_case import LLMTestCase

from evals.dataset.frames import load
from evals.dataset.frames.schemas import ScreenSample

from .compare import GROUPS, truth_for
from .solver import decode_frame


def select_frames(frame_ids: Sequence[str] = (), scene: str | None = None) -> list[ScreenSample]:
    """按 ID 与真值场合取交集；未知 ID 或空选择显式失败。"""
    frames = [frame for frame in load() if frame.wram]
    unknown = set(frame_ids) - {frame.sample_id for frame in frames}
    if unknown:
        raise ValueError(f"未知帧 ID：{sorted(unknown)}")
    selected = [
        frame
        for frame in frames
        if (not frame_ids or frame.sample_id in frame_ids)
        and (scene is None or (truth_for(frame, "scene") or {}).get("scene") == scene)
    ]
    if not selected:
        raise ValueError("没有符合筛选条件的帧")
    return selected


def build_cases(frames: Sequence[ScreenSample]) -> list[LLMTestCase]:
    """每帧只解码一次；快照与 ROM 错误上抛，真值空组原样保留。"""
    return [
        LLMTestCase(
            input=frame.sample_id,
            actual_output=decode_frame(frame).model_dump_json(),
            expected_output=json.dumps(
                {group: truth_for(frame, group) for group in GROUPS}, ensure_ascii=False
            ),
        )
        for frame in frames
    ]
