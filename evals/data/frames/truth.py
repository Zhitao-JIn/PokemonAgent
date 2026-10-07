"""唯一独立真值文件truth.jsonl：按sample_id挂到冻结帧，所有已标字段直接计分。"""

from pathlib import Path

from evals.data.frames.schemas import FrameTruth

TRUTH_FILE = Path(__file__).with_name("truth.jsonl")
TRUTH_GROUPS: tuple[str, ...] = ("screen_truth", "takeover_truth", "terrain_truth", "scene_truth")


def load_truth() -> dict[str, FrameTruth]:
    """读取全部独立真值；缺组保持缺组。后置条件：每个sample_id至多一行。"""
    if not TRUTH_FILE.exists():
        return {}
    rows = [
        FrameTruth.model_validate_json(line)
        for line in TRUTH_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {}
    for row in rows:
        by_id[row.sample_id] = row
    assert len({row.sample_id for row in rows}) == len(rows), "truth.jsonl 有重复 sample_id"
    return by_id


__all__ = ["TRUTH_FILE", "TRUTH_GROUPS", "load_truth"]
