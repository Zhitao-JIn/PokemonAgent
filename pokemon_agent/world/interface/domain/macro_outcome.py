"""`MacroOutcome`：一次宏调用的结果——成功 / 被拒 / 中途放弃 / 离开场合。

外加原因、状态摘要与逐步明细。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .task_scene import TaskScene


class MacroStatus(StrEnum):
    """宏的结局。`rejected` / `aborted` 是预期内结果，不是异常。"""

    DONE = "done"  # 执行到位，并按宏的约定收尾
    REJECTED = "rejected"  # 参数不合法（按回初态之后此刻的内存判），一个键都没按（回初态的 B 除外）
    ABORTED = "aborted"  # 执行中途没出现期望的变化，已按 B 回初态
    LEFT_SCENE = "left_scene"  # 回初态时场合已不是本宏的场合


class MacroReason(StrEnum):
    """`rejected` / `aborted` 的原因码（闭集）。"""

    UNKNOWN_MACRO = "unknown_macro"
    BAD_ARGS = "bad_args"
    UNKNOWN_ITEM = "unknown_item"
    NOT_ENOUGH_MONEY = "not_enough_money"
    BAG_FULL = "bag_full"
    QUANTITY_OUT_OF_RANGE = "quantity_out_of_range"
    NOT_IN_BAG = "not_in_bag"
    KEY_ITEM = "key_item"
    INVALID_NAME = "invalid_name"
    UNKNOWN_MOVE = "unknown_move"
    NO_PP = "no_pp"
    UNKNOWN_POKEMON = "unknown_pokemon"
    POKEMON_FAINTED = "pokemon_fainted"
    ALREADY_ACTIVE = "already_active"
    TARGET_REQUIRED = "target_required"
    CANNOT_USE = "cannot_use"
    REWIND_LIMIT = "rewind_limit"
    STEP_TIMEOUT = "step_timeout"
    UNEXPECTED_SCREEN = "unexpected_screen"


class MacroStep(BaseModel):
    """宏里的一步：按了什么、等了多少帧、期望什么、实际读到什么、通过没有。"""

    key: str = Field(description="按的键；只等不按时为空")
    frames: int = Field(ge=0, description="按完之后等了多少帧（到画面稳定或超时）")
    expect: str = Field(default="", description="期望出现的变化")
    actual: str = Field(default="", description="实际读到的")
    ok: bool = Field(default=True, description="期望是否达成")


class MacroOutcome(BaseModel):
    """一次宏调用的结果。"""

    scene: TaskScene = Field(description="调用时的场合")
    macro: str = Field(description="宏名")
    args: dict[str, str | int] = Field(default_factory=dict, description="参数原样")
    status: MacroStatus
    reason_code: MacroReason | None = Field(default=None, description="`done` 时为 None")
    reason: str = Field(default="", description="一句人话：为什么被拒 / 停在哪一步")
    summary: str = Field(default="", description="一行状态变化，如 `钱 3000→2000，POKé BALL +5`")
    steps: list[MacroStep] = Field(default_factory=list, description="逐步明细（每次都记）")

    def describe(self) -> str:
        """给下一轮决策与记忆看的一句话。"""
        call = f"{self.macro}({', '.join(str(v) for v in self.args.values())})"
        detail = self.summary if self.status is MacroStatus.DONE else self.reason
        return f"{call} → {self.status.value}" + (f"：{detail}" if detail else "")


__all__ = ["MacroOutcome", "MacroReason", "MacroStatus", "MacroStep"]
