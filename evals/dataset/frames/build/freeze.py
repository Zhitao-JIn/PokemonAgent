"""一次性采集原接管视图用例；运行 decode 时只读这里冻结的 RAM。"""

import base64
import zlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from evals.dataset.frames.schemas import ScreenLabel, ScreenSample
from evals.dataset.io import read_models
from evals.solvers.world_case import start_world, stop_world
from pokemon_agent.world import W_TILEMAP, TaskScene

from .storage import save_frames

SOURCES = Path(__file__).resolve().parents[1] / "sources"


class ViewCase(BaseModel):
    """采集现场与独立期望，state 相对 sources/states。"""

    case_id: str
    state: str
    scene: TaskScene
    expect: dict[str, Any]
    pre: tuple[str, ...] = ()
    on_screen: tuple[str, ...] = ()


def load_cases() -> list[ViewCase]:
    """读取八个冻结采集输入；损坏时抛 DatasetError。"""
    return read_models(SOURCES / "capture_cases.jsonl", ViewCase)


def freeze_takeover() -> None:
    """保留原手写期望；输出截图、缓冲、WRAM，与基础帧同一 schema。"""
    frames: list[ScreenSample] = []
    for case in load_cases():
        world = start_world(SOURCES / "states" / case.state, case.pre, case_id=case.case_id)
        try:
            perceived = world.perceive_task()
            memory = world._pyboy.memory
            truth = {
                **{f"view.{key}": value for key, value in case.expect.items()},
            }
            frames.append(
                ScreenSample(
                    sample_id=f"takeover:{case.case_id}",
                    source="takeover_snapshot",
                    category="",
                    in_battle=bool(perceived.ram and perceived.ram.in_battle),
                    tiles=[
                        [memory[W_TILEMAP + row * 20 + column] for column in range(20)]
                        for row in range(18)
                    ],
                    frame_png=perceived.frame_png,
                    label=ScreenLabel(scene=case.scene.value, overlay="none"),
                    takeover_truth=truth,
                    scene_truth={"scene": case.scene.value},
                    screen_truth={"screen_contains": list(case.on_screen)},
                    wram=base64.b64encode(zlib.compress(bytes(memory[0xC000:0xE000]), 9)).decode(),
                    note="原接管视图手写期望；场合与文字片段各归所属分组，地形未标",
                )
            )
        finally:
            stop_world(world)
    save_frames(frames, replace_sources=("takeover_snapshot",))


if __name__ == "__main__":
    freeze_takeover()
