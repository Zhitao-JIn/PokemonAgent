"""`CheckpointMark`：存档一族账（存档 / 恢复 / 失败）共用的正文素材。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CheckpointMark(BaseModel):
    """一次存档相关动作的要素。各本账取用的字段见 `direct/trace/render.py` 的渲染函数。"""

    checkpoint_id: str = Field(
        default="", description="存档 id（只进 checkpoint_error 正文；存档 / 恢复账的 id 在 meta）"
    )
    level: str = Field(min_length=1, description="存档点级别：run / episode / task")
    manifest_path: str = Field(
        default="", description="清单文件路径，相对进程启动目录（save / restore）"
    )
    stage: str = Field(default="", description="失败时哪一步：world / memory / graph / manifest")
