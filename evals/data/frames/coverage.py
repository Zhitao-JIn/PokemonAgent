"""核对冻结帧的完整输出标注；独立于准确率与审核资格。"""

import base64
import json
import zlib
from collections import Counter
from typing import Any

from pydantic import BaseModel, TypeAdapter

from pokemon_agent.world.interface.domain.screen_text import ScreenText
from pokemon_agent.world.interface.domain.takeover_view import TakeoverView

from .schemas import FrameTruth, ScreenSample
from .storage import DATASET_DIR
from .truth import load_truth


def absent_model_keys(model: BaseModel, raw: dict[str, Any], prefix: str) -> list[str]:
    """递归核对视图所有声明字段；模型默认值不能替原始标注补字段。"""
    missing = []
    for key in type(model).model_fields:
        path = f"{prefix}.{key}"
        if key not in raw:
            missing.append(path)
            continue
        value = getattr(model, key)
        if isinstance(value, BaseModel):
            missing.extend(absent_model_keys(value, raw[key], path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, BaseModel):
                    missing.extend(absent_model_keys(item, raw[key][index], f"{path}.{index}"))
    return missing


def missing_fields(frame: ScreenSample, truth: FrameTruth) -> list[str]:
    """每个适用输出键须有期望或 unresolved 原因；无地图的 terrain 为不适用。"""
    raw = zlib.decompress(base64.b64decode(frame.wram))
    map_loaded = bool(raw[0x1530] | raw[0x1531] << 8)
    required = {
        "scene_truth": {"scene", "covered_by_script", "at_start"},
        "screen_truth": set(ScreenText.model_fields) | {"overlay"},
        "takeover_truth": {"view"},
        "terrain_truth": {"map_id", "where", "facing", "walk_map", "neighbors"}
        if map_loaded
        else set(),
    }
    missing = [
        f"{group}.{key}"
        for group, keys in required.items()
        for key in sorted(keys)
        if key not in (getattr(truth, group) or {})
        and f"{group}.{key}" not in truth.unresolved_fields
    ]
    view = (truth.takeover_truth or {}).get("view")
    if view is not None:
        parsed = TypeAdapter(TakeoverView).validate_python(view)
        missing.extend(absent_model_keys(parsed, view, "takeover_truth.view"))
    return missing


def coverage_report() -> dict[str, Any]:
    """输出字段覆盖清单；待裁决单列，绝不计成已确定或已审核。"""
    truth = load_truth()
    frames = [
        ScreenSample.model_validate_json(line)
        for line in (DATASET_DIR / "v2" / "samples.jsonl").read_text("utf-8").splitlines()
    ]
    missing: dict[str, list[str]] = {}
    unresolved: dict[str, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    for frame in frames:
        row = truth.get(frame.sample_id)
        if row is None:
            missing[frame.sample_id] = ["truth row"]
            continue
        absent = missing_fields(frame, row)
        if absent:
            missing[frame.sample_id] = absent
        if row.unresolved_fields:
            unresolved[frame.sample_id] = row.unresolved_fields
        for group in ("scene_truth", "screen_truth", "takeover_truth", "terrain_truth"):
            for key in getattr(row, group) or {}:
                if "." not in key and key != "screen_contains":
                    counts[f"{group}.{key}"] += 1
    return {
        "frames": len(frames),
        "field_annotation_counts": dict(sorted(counts.items())),
        "unaccounted_fields": missing,
        "unresolved_fields": unresolved,
        "fully_determined_frames": len(frames) - len(set(missing) | set(unresolved)),
    }


if __name__ == "__main__":
    print(json.dumps(coverage_report(), ensure_ascii=False, indent=2))
