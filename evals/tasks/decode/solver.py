"""同一份冻结 RAM 一次跑完场合、文字、接管视图与地形解码，不调模型。"""

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from evals.core.snapshot import has_map, snapshot_of
from evals.core.world_case import ROM
from evals.data.frames.schemas import ScreenSample
from pokemon_agent.world import (
    TAKEOVER_SCENES,
    at_start,
    classify_scene,
    overlay_of,
    read_screen_text,
)
from pokemon_agent.world.ram import read_terrain
from pokemon_agent.world.scripts.takeover import takeover_entries, takeover_view

from .schemas import DecodeRecord, DecodeRun


def decode_frame(sample: ScreenSample) -> DecodeRun:
    """前置条件：帧有 WRAM；全部解码器读取同一时刻的只读内存。"""
    _, memory = snapshot_of(sample)
    text = read_screen_text(memory)
    scene = classify_scene(text, memory)
    view = takeover_view(scene, text, memory, ROM.read_bytes())
    terrain: dict = {}
    if has_map(sample):
        decoded = read_terrain(memory)
        terrain = {
            "map_id": decoded.map_id,
            "where": decoded.place().render(),
            "facing": decoded.facing or "",
            "walk_map": decoded.render(),
            "neighbors": decoded.render_neighbors(),
        }
    return DecodeRun(
        scene={
            "scene": scene.value,
            "covered_by_script": bool(takeover_entries(scene)),
            "at_start": at_start(text, scene) if scene in TAKEOVER_SCENES else None,
        },
        screen={**text.model_dump(mode="json"), "overlay": overlay_of(text).value},
        takeover={
            "view": view.model_dump(mode="json") if view else None,
        },
        terrain=terrain,
    )


@solver
def decode_solver() -> Solver:
    """每帧只解码一次；快照损坏上抛为 sample error。"""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        store_as(DecodeRecord).run = decode_frame(
            ScreenSample.model_validate(state.metadata["frame"])
        )
        return state

    return solve
