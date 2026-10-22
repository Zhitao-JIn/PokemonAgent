"""决定 H（2026-10-22）：评测自有的真值文本格式与 world 的三个 `render` 方法逐字节相等。

真值是冻结的**文本**（`where` / `walk_map` / `neighbors`），解码侧不能改成比结构，
所以把世界那三个渲染方法复制进 `evals/decode/terrain_text.py`。这条测试遍历
**全部带地形真值**的冻结帧，证明复制件与原件逐字节相同——相等之后，world 里的
那份才能随 CP6b 删掉。
"""

from __future__ import annotations

from evals.dataset.frames import load as load_frames
from evals.dataset.frames.snapshot import has_map, snapshot_of
from evals.decode.terrain_text import render_neighbors, render_walk_map, render_where
from pokemon_agent.world.ram import read_terrain


def test_copied_terrain_text_is_byte_equal_to_the_world_methods() -> None:
    samples = load_frames()
    frames = [frame for frame in samples if frame.terrain_truth is not None and has_map(frame)]
    assert all(not frame.terrain_truth for frame in samples if not has_map(frame))
    assert frames, "没有带地形真值的冻结帧"

    for frame in frames:
        _, memory = snapshot_of(frame)
        terrain = read_terrain(memory)
        assert render_where(terrain.place()) == terrain.place().render(), frame.sample_id
        assert render_walk_map(terrain) == terrain.render(), frame.sample_id
        assert render_neighbors(terrain) == terrain.render_neighbors(), frame.sample_id
