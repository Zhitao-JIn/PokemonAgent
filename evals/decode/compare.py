"""逐字段的纯比较契约；缺真值为 N，显式空值仍计分。"""

from typing import Any, Literal

from pydantic import BaseModel

from evals.dataset.frames.schemas import ScreenSample

Group = Literal["scene", "screen", "takeover", "terrain"]
GROUPS: tuple[Group, ...] = ("scene", "screen", "takeover", "terrain")


class Verdict(BaseModel):
    """C 为相等，I 为不相等，N 为未标注。"""

    value: Literal["C", "I", "N"]
    reason: str


def at_path(data: object, path: str) -> object:
    """点路径取值；不存在返回 None。"""
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def contains_path(data: object, path: str) -> bool:
    """区分缺键与存在的 None；支持字典与列表的点路径。"""
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return False
    return True


def truth_for(frame: ScreenSample, group: Group) -> dict[str, Any] | None:
    """只取独立真值，不从预标注回退。"""
    return getattr(frame, f"{group}_truth")


def field_verdict(
    got_group: dict[str, Any], truth_group: dict[str, Any] | None, key: str
) -> Verdict:
    """比较一个已标键；缺标返回 N，空值按值与键存在性比较。

    调用方保证组是 JSON 对象；点路径保持旧比较语义，不调用模型。
    """
    if not truth_group or key not in truth_group:
        return Verdict(value="N", reason="这一帧未标此字段")
    want = truth_group[key]
    if key == "screen_contains":
        wrong = [f"屏上缺少 {text!r}" for text in want if text not in got_group.get("screen", "")]
    else:
        wrong = (
            [f"{key}: {at_path(got_group, key)!r} ≠ {want!r}"]
            if not contains_path(got_group, key) or at_path(got_group, key) != want
            else []
        )
    return Verdict(value="I" if wrong else "C", reason="；".join(wrong) or "标注字段符合")
