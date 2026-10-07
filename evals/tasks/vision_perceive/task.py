"""视觉节点与视觉模型：仅传截图，只判人工核过的视觉字段。"""

from __future__ import annotations

from collections import Counter

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from evals.core.frames import load_frames
from evals.data.frames.schemas import ScreenSample
from evals.runconfig import load_config
from evals.tasks.vision_perceive.scorer import perceive_scorer
from evals.tasks.vision_perceive.solver import perceive_solver
from pokemon_agent.env import load_env_file

DATASET_VERSION = "v2"
"""唯一带 WRAM 快照的版本（v1 只有截图与屏幕缓冲，接不进感知节点）。"""
SAMPLE_TIME_LIMIT = 120


def to_sample(sample: ScreenSample) -> Sample:
    """帧 → inspect Sample：input 是截图（View 里能看），样本整份进 metadata。"""
    return Sample(
        id=sample.sample_id,
        input=sample.frame_png,
        target=sample.label.overlay,
        metadata={
            "scene": sample.label.scene,
            "label_checked": sample.label_checked,
            "sample": sample.model_dump(mode="json"),
        },
    )


def first_per_scene(frames: list[ScreenSample], n: int) -> list[ScreenSample]:
    """每种标注场合只留前 `n` 帧（保序）。"""
    seen: Counter[str] = Counter()
    kept: list[ScreenSample] = []
    for frame in frames:
        seen[frame.label.scene] += 1
        if seen[frame.label.scene] <= n:
            kept.append(frame)
    return kept


@task
def vision_perceive(
    vision_model: str | None = None,
    per_scene: int | None = None,
    checked_only: bool = True,
) -> Task:
    """每帧一次仅截图的视觉感知，逐字段判。

    `vision_model` 缺省取 `evals/config.json` 的 `models.vision_model`；`per_scene=N` 每种标注场合
    只取前 N 帧（冒烟用）；`checked_only` 只跑人工核过标注的帧。
    """
    load_env_file()  # 视觉 provider 的密钥在仓库根的 .env 里（与 build.py 同一个入口）
    model = vision_model or str(load_config()["models"]["vision_model"])
    frames = [
        s
        for s in load_frames(DATASET_VERSION)
        if s.source not in {"takeover_snapshot", "terrain_snapshot"}
    ]
    frames = [s for s in frames if s.label_checked or not checked_only]
    if per_scene is not None:
        frames = first_per_scene(frames, per_scene)
    return Task(
        dataset=[to_sample(s) for s in frames],
        solver=perceive_solver(model),
        scorer=perceive_scorer(),
        model="none",
        time_limit=SAMPLE_TIME_LIMIT,
        fail_on_error=False,
        metadata={"vision_model": model, "dataset_version": DATASET_VERSION, "frames": len(frames)},
    )
