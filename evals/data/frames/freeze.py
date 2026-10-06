"""一次性采集原接管视图用例；运行 decode 时只读这里冻结的 RAM。"""

import base64
import zlib

from evals.core.frames import EXTRA_FRAMES
from evals.core.world_case import start_world, stop_world
from evals.data.screen_reading.schemas import ScreenLabel, ScreenSample
from pokemon_agent.world import W_TILEMAP

from .capture_cases import CASES


def freeze_takeover() -> None:
    """保留原手写期望；输出截图、缓冲、WRAM，与基础帧同一 schema。"""
    frames: list[ScreenSample] = []
    for case in CASES:
        world = start_world(case.state, case.pre, case_id=case.case_id)
        try:
            perceived = world.perceive_task()
            memory = world._pyboy.memory
            truth = {
                "scene": case.scene.value,
                "screen_contains": list(case.on_screen),
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
                    wram=base64.b64encode(zlib.compress(bytes(memory[0xC000:0xE000]), 9)).decode(),
                    note="原接管视图手写期望；文字组与地形组没有标注",
                )
            )
        finally:
            stop_world(world)
    EXTRA_FRAMES.parent.mkdir(parents=True, exist_ok=True)
    EXTRA_FRAMES.write_text("\n".join(f.model_dump_json() for f in frames) + "\n", encoding="utf-8")


if __name__ == "__main__":
    freeze_takeover()
