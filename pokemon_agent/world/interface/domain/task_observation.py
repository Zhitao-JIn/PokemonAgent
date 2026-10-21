"""task 层的观测（`TaskObservation`）：只读内存与屏幕缓冲、不调模型的那一档，多一个场合。

与 episode 层的 `Observation` 是两种观测。形状上沿用 `Observation` 的全部字段
（位置、状态行、`Facts`），再加 task 层自己的 `scene`，仅开放脚本的场合另带视图 `takeover`。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SerializerFunctionWrapHandler, computed_field, model_serializer

from .observation import Observation
from .takeover_view import TakeoverView
from .task_scene import SCRIPT_ONLY_SCENES, TaskScene


class TaskObservation(Observation):
    """**task 层的一帧**：RAM 档观测 + 场合。"""

    scene: TaskScene = Field(description="这一帧属于哪个场合（`world/scene.py::classify_scene`）")
    takeover: TakeoverView | None = Field(
        default=None, description="当前场合的业务视图；不适用或尚无对应视图时为 None"
    )
    menu_decode_complete: bool | None = Field(
        default=None,
        description="ScreenText.covered 的选单切分完整性；None 表示未测，"
        "不能证明整帧识别正确或画面稳定",
    )

    @computed_field
    @property
    def covered_by_script(self) -> bool:
        """本场合由脚本操作，包含子菜单；与是否已在初态无关。

        从场合派生，不接受独立赋值。开放按键的场合即使有可选脚本也返回 False。
        """
        return self.scene in SCRIPT_ONLY_SCENES

    @computed_field
    @property
    def selected_map_location(self) -> str | None:
        """城镇地图顶行选中地点；不是主角位置。非地图或没有明确标题时为 None。"""
        if self.scene is not TaskScene.BAG:
            return None
        lines = [line.strip(" ·") for line in self.facts.screen.splitlines()]
        named = [line for line in lines if any(character.isalpha() for character in line)]
        if lines and len(named) == 1 and lines[0] == named[0]:
            return named[0]
        return None

    @model_serializer(mode="wrap")
    def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """历史观测没有结构化增量时保留原信封。"""
        data = handler(self)
        if not self.facts.model_fields_set.intersection(
            (
                "neighbor_cells",
                "cells",
                "option_grid",
                "cursor_cell",
                "option_annotations",
                "battle_status",
                "terrain_visible",
            )
        ):
            data.pop("observation_flags", None)
        return data

    @computed_field
    @property
    def observation_flags(self) -> list[str]:
        """同帧的结构化限制标志，不包含给模型看的措辞。"""
        flags: list[str] = []
        if not (self.facts.screen or self.facts.dialog_text or self.facts.options):
            flags.append("no_text")
        if self.menu_decode_complete is False:
            flags.append("incomplete_menu")
        if self.covered_by_script and self.takeover is None:
            flags.append("missing_takeover")
        if self.scene is TaskScene.TRANSITION:
            flags.append("transition")
        return flags

    @computed_field
    @property
    def observation_notes(self) -> list[str]:
        """显示相关的观测限制；缺文字、切分不全和业务视图缺失分别说明，不推断稳定性。"""
        notes: list[str] = []
        if not (self.facts.screen or self.facts.dialog_text or self.facts.options):
            notes.append("未解码出屏幕文字，不能据此判断界面已结束")
        if self.menu_decode_complete is False:
            if self.covered_by_script:
                notes.append("选单切分不完整，接管参数以业务视图为准；缺选项不表示没有选单")
            else:
                notes.append("选单切分不完整，不能用空选项判断没有选单；以 screen 核对文字")
        if self.covered_by_script and self.takeover is None:
            notes.append("接管业务视图缺失，脚本参数依据可能不足；覆盖标志不代表参数已知")
        if self.scene is TaskScene.TRANSITION:
            notes.append("当前分类为过场，单帧不能判断是否稳定；需新观测确认")
        return notes


__all__ = ["TaskObservation"]
