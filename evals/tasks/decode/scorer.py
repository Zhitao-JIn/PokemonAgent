"""四个 scorer 分组核标注；没有标注的组记 NOANSWER、不进分母。"""

from typing import Any, Literal

from inspect_ai.scorer import NOANSWER, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.core.judged import judged_accuracy, judged_count
from evals.data.frames.schemas import ScreenSample

from .schemas import DecodeRecord

Group = Literal["scene", "screen", "takeover", "terrain"]
BASELINE_FIELDS = (
    "scene",
    "overlay",
    "dialog_text",
    "options",
    "option_grid",
    "option_details",
    "cursor",
    "cursor_cell",
    "has_cursor",
    "quantity_box",
    "in_battle",
    "strict_dialog",
    "screen",
)


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
    """只读取加载器挂上的独立真值；预标和采集来源不参与评分。"""
    return getattr(frame, f"{group}_truth")


def contains_path(data: object, path: str) -> bool:
    """区分字段不存在与存在但值为 None，防止漏输出获得空值标注的通过分。"""
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return False
    return True


def compare_group(got: dict[str, Any], truth: dict[str, Any] | None) -> Score:
    """只比较标注的字段，空标注与未标注都记 N；存在的 None 值仍需输出该键。"""
    if not truth:
        return Score(value=NOANSWER, explanation="这一帧未标此字段组")
    wrong = [
        f"{key}: {at_path(got, key)!r} ≠ {want!r}"
        for key, want in truth.items()
        if key != "screen_contains"
        if not contains_path(got, key) or at_path(got, key) != want
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
def scene_scorer() -> Scorer:
    """判场合、脚本覆盖与初态；脚本实际恢复与执行由 world_actions 验证。"""
    return decode_scorer("scene")


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


@scorer(
    metrics={key: [judged_accuracy(), judged_count()] for key in (*BASELINE_FIELDS, "all_fields")}
)
def generic_decoder_scorer() -> Scorer:
    """逐字段统计通用解码；控制字段不计分，缺真值为N，13字段全可判才统计整帧。"""

    async def score(state: TaskState, target: Target) -> Score:
        run = store_as(DecodeRecord).run
        assert run is not None, "solver 未写解码结果"
        frame = ScreenSample.model_validate(state.metadata["frame"])
        values: dict[str, str] = {}
        wrong = []
        for field in BASELINE_FIELDS:
            group: Group = "scene" if field == "scene" else "screen"
            truth = truth_for(frame, group) or {}
            expected = {field: truth[field]} if field in truth else None
            verdict = compare_group(getattr(run, group), expected)
            values[field] = str(verdict.value)
            if verdict.value == "I":
                wrong.append(verdict.explanation)
        values["all_fields"] = (
            ("I" if "I" in values.values() else "C")
            if NOANSWER not in values.values()
            else NOANSWER
        )
        return Score(value=values, explanation="；".join(wrong) or "已标通用字段符合参考真值")

    return score
