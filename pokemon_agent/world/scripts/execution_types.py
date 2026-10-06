"""脚本的结局、业务失败码与步骤记录。"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ScriptStatus(StrEnum):
    """脚本的结局。`rejected` / `aborted` 是预期内结果，不是异常。"""

    DONE = "done"
    REJECTED = "rejected"
    ABORTED = "aborted"
    LEFT_SCENE = "left_scene"


class ScriptReason(StrEnum):
    """`rejected` / `aborted` 的原因码（闭集）。"""

    UNKNOWN_SCRIPT = "unknown_script"
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


class ScriptStep(BaseModel):
    """脚本里的一步：按了什么、等了多少帧、期望什么、实际读到什么、通过没有。"""

    key: str = Field(description="按的键；只等不按时为空")
    frames: int = Field(ge=0, description="按完之后等了多少帧（到画面稳定或超时）")
    expect: str = Field(default="", description="期望出现的变化")
    actual: str = Field(default="", description="实际读到的")
    ok: bool = Field(default=True, description="期望是否达成")
