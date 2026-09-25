"""`CheckpointMark`：存档一族账（存档 / 恢复 / 世界快照 / 封存 / 失败）共用的正文素材。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CheckpointMark(BaseModel):
    """一次存档相关动作的要素。各本账取用的字段见 `tools/trace/render.py` 的渲染函数。"""

    checkpoint_id: str = Field(default="", description="存档 id")
    level: str = Field(
        min_length=1, description="存档点级别：run / episode / task（task 只有世界快照）"
    )
    manifest_path: str = Field(default="", description="清单文件路径（save / restore）")
    world_path: str = Field(default="", description="世界快照路径（world_snapshot）")
    count: int = Field(default=0, ge=0, description="封存了几条账（trace_sealed）")
    parent_branch: str = Field(default="", description="恢复时：存档所在的父执行线")
    parent_last_event_uuid: str = Field(default="", description="恢复时：父执行线的分叉点事件")
    to_task: str = Field(default="", description="恢复时：回放到哪个 task 开局（空 = 不回放）")
    stage: str = Field(
        default="",
        description="失败时哪一步：world / memory / graph / manifest / world_snapshot / seal",
    )
