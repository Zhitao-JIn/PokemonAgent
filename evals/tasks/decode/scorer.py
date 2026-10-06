"""三个 scorer 分组核人工标注；没有标注的组记 NOANSWER、不进分母。"""

from typing import Any, Literal

from inspect_ai.scorer import NOANSWER, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.core.judged import judged_accuracy, judged_count
from evals.data.screen_reading.schemas import ScreenSample

from .schemas import DecodeRecord

Group = Literal["screen", "takeover", "terrain"]


def at_path(data: object, path: str) -> object:
    """点路径取结构化标注字段；不存在返回 None。"""
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def truth_for(frame: ScreenSample, group: Group) -> dict[str, Any] | None:
    """明确标注优先；基础数据只有人工核过的帧可用于文字真值。"""
    truth = getattr(frame, f"{group}_truth")
    if truth is None and group == "screen" and frame.label_checked:
        truth = frame.label.model_dump(include={"dialog_text", "options", "cursor"})
    return truth


def compare_group(got: dict[str, Any], truth: dict[str, Any] | None) -> Score:
    """只比较标注的字段，空标注与未标注都记 N。"""
    if not truth:
        return Score(value=NOANSWER, explanation="这一帧未标此字段组")
    wrong = [
        f"{key}: {at_path(got, key)!r} ≠ {want!r}"
        for key, want in truth.items()
        if key != "screen_contains"
        if at_path(got, key) != want
    ]
    wrong += [
        f"屏上缺少 {text!r}"
        for text in truth.get("screen_contains", [])
        if text not in got.get("screen", "")
    ]
    return Score(value="I" if wrong else "C", explanation="；".join(wrong) or "标注字段全部符合")


def decode_scorer(group: Group) -> Scorer:
    """每个 scorer 只判一组，共享 solver 的产物。"""

    async def score(state: TaskState, target: Target) -> Score:
        run = store_as(DecodeRecord).run
        assert run is not None, "solver 未写解码结果"
        frame = ScreenSample.model_validate(state.metadata["frame"])
        return compare_group(getattr(run, group), truth_for(frame, group))

    return score


@scorer(metrics=[judged_accuracy(), judged_count()])
def screen_text_scorer() -> Scorer:
    """只判 ScreenText 字段组。"""
    return decode_scorer("screen")


@scorer(metrics=[judged_accuracy(), judged_count()])
def takeover_view_scorer() -> Scorer:
    """只判接管视图字段组。"""
    return decode_scorer("takeover")


@scorer(metrics=[judged_accuracy(), judged_count()])
def terrain_scorer() -> Scorer:
    """只判地形与位置字段组。"""
    return decode_scorer("terrain")
