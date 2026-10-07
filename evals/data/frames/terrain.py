"""按既有存档说明冻结地形标注；真值不从待测解码器的输出生成。"""

import base64
import zlib
from typing import Any

from pydantic import BaseModel

from evals.data.frames.schemas import ScreenLabel, ScreenSample
from evals.solvers.world_case import start_world, stop_world
from pokemon_agent.world import W_TILEMAP

from .storage import save_frames

BASIS = "evals/tasks/world_script_execute/regular_batch_1.py 文件顶层存档速记"


class TerrainCase(BaseModel):
    """独立写出的存档事实；未核过的完整 walk_map 不标。"""

    case_id: str
    state: str
    truth: dict[str, Any]
    basis: str


CASES: tuple[TerrainCase, ...] = (
    TerrainCase(
        case_id="route1_ledge",
        state="knowledge/knowledge_movement_obstacle.state",
        truth={
            "map_id": 12,
            "where": "全局坐标 地图12 x=9 y=12",
            "facing": "south",
            "neighbors": "北 . 南 v 西 . 东 .",
        },
        basis=f"{BASIS}：OBSTACLE，(9,12) 面南，南邻是向南台阶，其余邻格开阔",
    ),
    TerrainCase(
        case_id="route1_grass",
        state="knowledge/knowledge_wild_encounter.state",
        truth={
            "map_id": 12,
            "where": "全局坐标 地图12 x=13 y=8",
            "facing": "east",
            "neighbors": "北 G 南 G 西 G 东 G",
        },
        basis=f"{BASIS}：GRASS，(13,8) 面东，四邻全为高草",
    ),
)


def freeze_terrain() -> None:
    """从注明的存档只采截图与内存；独立期望原样写入，不抄解码结果。"""
    frames: list[ScreenSample] = []
    for case in CASES:
        world = start_world(case.state, (), case_id=case.case_id)
        try:
            memory = world._pyboy.memory
            frames.append(
                ScreenSample(
                    sample_id=f"terrain:{case.case_id}",
                    source="terrain_snapshot",
                    category="",
                    in_battle=False,
                    tiles=[
                        [memory[W_TILEMAP + row * 20 + column] for column in range(20)]
                        for row in range(18)
                    ],
                    frame_png=world.perceive_task().frame_png,
                    label=ScreenLabel(scene="walk", overlay="none"),
                    terrain_truth=case.truth,
                    wram=base64.b64encode(zlib.compress(bytes(memory[0xC000:0xE000]), 9)).decode(),
                    note=f"地形事实依据：{case.basis}；文字、接管与完整 walk_map 未标",
                )
            )
        finally:
            stop_world(world)
    save_frames(frames, replace_sources=("terrain_snapshot",))


if __name__ == "__main__":
    freeze_terrain()
