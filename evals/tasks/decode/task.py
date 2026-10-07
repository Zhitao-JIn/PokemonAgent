"""decode：一次机械解码，四个 scorer，全部使用冻结帧。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.dataset.frames import load as load_frames
from evals.scorers.decode import (
    generic_decoder_scorer,
    scene_scorer,
    screen_text_scorer,
    takeover_view_scorer,
    terrain_scorer,
)
from evals.solvers.decode import decode_solver


@task
def decode(version: str = "v2", baseline_only: bool = False) -> Task:
    """默认使用全部独立真值；通用基线只统计13字段。"""
    return Task(
        dataset=[
            Sample(id=f.sample_id, input=f.sample_id, metadata={"frame": f.model_dump(mode="json")})
            for f in load_frames(version)
            if f.wram
        ],
        solver=decode_solver(),
        scorer=[generic_decoder_scorer()]
        if baseline_only
        else [scene_scorer(), screen_text_scorer(), takeover_view_scorer(), terrain_scorer()],
        metadata={
            "reference_scope": "all_truth",
            "metric_scope": "generic_13_fields" if baseline_only else "full_groups",
        },
        model="none",
        fail_on_error=False,
    )
