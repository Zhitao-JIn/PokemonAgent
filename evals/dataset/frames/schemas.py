"""帧数据集的契约：样本、标注、补充真值、模型回答、逐项打分、报告头。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pokemon_agent.world import SCRIPT_ONLY_SCENES as _TAKEOVER
from pokemon_agent.world import TaskScene

Overlay = Literal["none", "dialog", "choice"]
Source = Literal[
    "observation_check", "probe_0926", "capture_0926", "takeover_snapshot", "terrain_snapshot"
]
TruthGroup = Literal["screen_truth", "takeover_truth", "terrain_truth", "scene_truth"]
FIELDS: tuple[str, ...] = (
    "scene",
    "at_start",
    "overlay",
    "dialog_text",
    "options",
    "cursor",
    "quantity",
)
"""逐项打分的字段。`scene` 只打分类器（解码直出一列）；`quantity` 只在标注有值的帧上打分；
接管类界面（`SCRIPT_ONLY_SCENES`）只打 `scene` 与 `at_start`（是否在脚本的初态）。"""

NORMAL_SCENES: tuple[str, ...] = tuple(s.value for s in TaskScene if s not in _TAKEOVER)
"""开放按键的场合（world 的 `TaskScene` 里接管以外的）：JEV 一键一决策，要测读得对不对。"""
SCRIPT_ONLY_SCENES: tuple[str, ...] = tuple(s.value for s in TaskScene if s in _TAKEOVER)
"""机械接管的场合（world 的 `SCRIPT_ONLY_SCENES`）：只测分类对不对、是否在初态。
场合与脚本、初态定义见 `docs/perceive/spec.md` 第三、五节。"""


class ScreenLabel(BaseModel):
    """一帧屏幕上真正写着什么（人工标注）。"""

    scene: str = Field(
        default="", description="界面种类（`NORMAL_SCENES` / `SCRIPT_ONLY_SCENES`）；v1 没标为空"
    )
    at_start: bool | None = Field(
        default=None,
        description="是否在脚本的初态（见 `SCRIPT_ONLY_SCENES`）；开放按键的场合为 None",
    )
    overlay: Overlay
    dialog_text: str = ""
    options: list[str] = Field(default_factory=list)
    cursor: str = ""
    quantity: int | None = Field(default=None, description="数量框里的数；没有数量框为 None")


class ScreenSample(BaseModel):
    """一帧样本。"""

    sample_id: str
    source: Source
    category: str = Field(description="0926 探测帧的 A/B/C/D；observation_check 帧为空")
    in_battle: bool
    tiles: list[list[int]] = Field(description="18 行 × 20 列 tile id")
    frame_png: str = Field(description="截图 data URI（只给人看，不进 prompt）")
    label: ScreenLabel
    note: str = ""
    label_checked: bool = Field(default=False, description="标注经人工核对过")
    wram: str = Field(default="", description="整块 WRAM（0xC000–0xDFFF）zlib + base64；v1 为空")
    screen_truth: dict[str, Any] | None = None
    takeover_truth: dict[str, Any] | None = None
    terrain_truth: dict[str, Any] | None = None
    scene_truth: dict[str, Any] | None = None


class FrameTruth(BaseModel):
    """`truth.jsonl` 的一行：每个解码输出字段都需独立期望或明确的无法判定原因。

    `labeler`：谁标的（如 `claude_from_ram`）；存在的独立标注直接用于评分。
    各 `*_truth` 与帧上同名字段同形，只比对其中出现的键。
    `scene_truth` 的 `covered_by_script` 表示脚本覆盖本场合，子菜单仍为 True；
    与 `at_start` 分开，不以存在任意可选脚本作为覆盖判据。
    """

    sample_id: str
    labeler: str
    unresolved_fields: dict[str, str] = Field(
        default_factory=dict, description="无法独立确定的输出路径及原因，不用空值伪装真值"
    )
    note: str = ""
    screen_truth: dict[str, Any] | None = None
    takeover_truth: dict[str, Any] | None = None
    terrain_truth: dict[str, Any] | None = None
    scene_truth: dict[str, Any] | None = None


class ScreenAnswer(BaseModel):
    """模型（或解码直出）给出的读屏结果。"""

    scene: str = ""
    at_start: bool | None = None
    overlay: Overlay | None = None
    dialog_text: str = ""
    options: list[str] = Field(default_factory=list)
    cursor: str = ""
    quantity: int | None = None


class SampleScore(BaseModel):
    """一帧的结果：两种读法各自的回答与逐项对错。"""

    sample_id: str
    source: Source
    category: str
    bucket: str = Field(
        description="按解码结果分的界面桶：纯对话 / 选单 / 选单(解码切不全) / 数量框 / 无叠加 …"
    )
    decoded: ScreenAnswer
    decoded_ok: dict[str, bool]
    model: ScreenAnswer | None = None
    model_ok: dict[str, bool] | None = None
    model_error: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ScreenHeader(BaseModel):
    """一次跑的口径。"""

    report_id: str
    created_at: str
    git_commit: str
    git_dirty: bool
    model: str = Field(description="文本模型型号；只算解码直出时为空")
    prompt_sha256: str
    samples_sha256: str
    dataset_version: str


__all__ = [
    "FIELDS",
    "FrameTruth",
    "NORMAL_SCENES",
    "SCRIPT_ONLY_SCENES",
    "Overlay",
    "SampleScore",
    "ScreenAnswer",
    "ScreenHeader",
    "ScreenLabel",
    "ScreenSample",
    "Source",
    "TruthGroup",
]
