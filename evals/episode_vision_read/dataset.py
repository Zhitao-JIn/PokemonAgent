"""共用冻结帧的视觉选择与一次读屏用例；调用不通的帧单独列出。"""

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from deepeval.test_case import LLMTestCase
from pydantic import BaseModel

from evals.dataset.frames import ScreenSample
from evals.dataset.frames import load as load_frames
from pokemon_agent.world import VisionProvider

from .compare import truth_fields
from .solver import PerceiveRun, ProviderUnreachable, perceive_sample


class ProviderFailure(BaseModel):
    """仅记录基础设施调用失败，不造评测用例。"""

    sample_id: str
    reason: str


def select_frames(per_scene: int | None = None, checked_only: bool = True) -> list[ScreenSample]:
    """与旧 task 相同的筛选与顺序；per_scene 为正时按标注场合限量。"""
    assert per_scene is None or per_scene > 0
    frames = [
        sample
        for sample in load_frames("v2")
        if sample.source not in {"takeover_snapshot", "terrain_snapshot"}
        and (sample.label_checked or not checked_only)
    ]
    if per_scene is None:
        return frames
    seen: Counter[str] = Counter()
    kept: list[ScreenSample] = []
    for frame in frames:
        seen[frame.label.scene] += 1
        if seen[frame.label.scene] <= per_scene:
            kept.append(frame)
    return kept


def output_for(run: PerceiveRun) -> dict[str, Any]:
    """解析失败只有 parsed/failure，成功时带五个视觉字段。"""
    output: dict[str, Any] = {"parsed": run.facts is not None, "failure": run.failure}
    if run.facts is not None:
        output.update(
            {
                key: getattr(run.facts, key)
                for key in ("scene", "overlay", "dialog_text", "options", "cursor")
            }
        )
    return output


def case_for(frame: ScreenSample, run: PerceiveRun) -> LLMTestCase:
    """仅用冻结人工标注造期望；模型输出不参与适用字段选择。"""
    return LLMTestCase(
        name=frame.sample_id,
        input=frame.sample_id,
        actual_output=json.dumps(output_for(run), ensure_ascii=False),
        expected_output=json.dumps(truth_fields(frame), ensure_ascii=False),
    )


def build_cases(
    frames: list[ScreenSample], vision: VisionProvider, workers: int = 4
) -> tuple[list[LLMTestCase], list[ProviderFailure]]:
    """线程内读屏；只有 ProviderUnreachable 被排除，其他错误直接上抛。"""
    assert workers > 0

    def perceive(frame: ScreenSample) -> LLMTestCase | ProviderFailure:
        try:
            return case_for(frame, perceive_sample(frame, vision))
        except ProviderUnreachable as error:
            return ProviderFailure(sample_id=frame.sample_id, reason=str(error))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(perceive, frames))
    return (
        [result for result in results if isinstance(result, LLMTestCase)],
        [result for result in results if isinstance(result, ProviderFailure)],
    )
