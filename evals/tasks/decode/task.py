"""decode：一次机械解码，三个 scorer，全部使用冻结帧。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.core.frames import load_frames
from evals.tasks.decode.scorer import screen_text_scorer, takeover_view_scorer, terrain_scorer
from evals.tasks.decode.solver import decode_solver


@task
def decode(version: str = "v2") -> Task:
    """加载有 RAM 的帧；无组标注时该 scorer 不进分母。"""
    return Task(
        dataset=[
            Sample(id=f.sample_id, input=f.sample_id, metadata={"frame": f.model_dump(mode="json")})
            for f in load_frames(version)
            if f.wram
        ],
        solver=decode_solver(),
        scorer=[screen_text_scorer(), takeover_view_scorer(), terrain_scorer()],
        model="none",
        fail_on_error=False,
    )
