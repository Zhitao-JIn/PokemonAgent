"""三项帧测评共用的冻结数据集；加载不推进模拟器、不现场生成真值。"""

import json
from pathlib import Path

from evals.data.frames.interpret import INTERPRET_INPUTS
from evals.data.frames.terrain import TERRAIN_FRAMES
from evals.data.screen_reading.build import load_samples
from evals.data.screen_reading.schemas import ScreenSample

EXTRA_FRAMES = Path(__file__).parents[1] / "data" / "frames" / "takeover.jsonl"


def load_frames(version: str = "v2") -> list[ScreenSample]:
    """读取基础帧和接管冻结帧；没有标某组的帧保持 None。"""
    frames = load_samples(version)
    for path in (EXTRA_FRAMES, TERRAIN_FRAMES):
        if path.exists():
            frames += [
                ScreenSample.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            ]
    if INTERPRET_INPUTS.exists():
        inputs = json.loads(INTERPRET_INPUTS.read_text(encoding="utf-8"))
        frames = [
            frame.model_copy(update={"interpret_input": inputs.get(frame.sample_id)})
            for frame in frames
        ]
    return frames
