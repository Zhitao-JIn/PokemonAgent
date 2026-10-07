"""脚本调用样本与独立期望的冻结契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROBE_KEYS: tuple[str, ...] = ("map_id", "x", "y", "facing", "scene", "money", "party_hp_missing")
BAG_PREFIX = "bag:"
EventOutcome = Literal["dialog", "warp", "still"]


class TakeoverCheck(BaseModel):
    """一条声明式核对，kind 与原核对工厂一一对应，args 原样冻结。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "money",
        "bag",
        "scene",
        "left",
        "battle_start",
        "in_play",
        "foe_hurt",
        "shop_start",
        "pc",
        "order",
        "box",
        "knows",
    ]
    args: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)


def is_probe_key(key: str) -> bool:
    """`key` 是否在真值词表里。"""
    return key in PROBE_KEYS or (key.startswith(BAG_PREFIX) and len(key) > len(BAG_PREFIX))


class ScriptExpect(BaseModel):
    """一条用例的期望。

    `data` 对报告 `data` 做子集匹配（只写标量）；`events` 是报告事件 outcome 序列里
    必须**按序出现**的子序列；`dialog` 是对话事件文字（按序拼起来）里必须出现的片段；
    `after` 是收尾帧的取值，`delta` 是收尾帧减开跑帧的整数差。
    契约：真值面至少写一项（只核自报的用例等于让脚本给自己打分）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    code: str
    data: dict[str, str | int | bool] = Field(default_factory=dict)
    events: list[EventOutcome] = Field(default_factory=list)
    dialog: list[str] = Field(default_factory=list)
    after: dict[str, str | int] = Field(default_factory=dict)
    delta: dict[str, int] = Field(default_factory=dict)
    checks: list[TakeoverCheck] = Field(default_factory=list)
    status: str | None = None
    summary: str = ""

    @model_validator(mode="after")
    def _truth_declared(self) -> ScriptExpect:
        """真值面非空、键都在词表里。"""
        if not (self.after or self.delta or self.checks or self.status is not None):
            raise ValueError("用例必须声明至少一项真值期望（after / delta）")
        bad = [k for k in [*self.after, *self.delta] if not is_probe_key(k)]
        if bad:
            raise ValueError(f"真值键不在词表里：{bad}")
        return self


class ScriptCase(BaseModel):
    """一条用例：存档 + 开跑前的键 + 一次脚本调用 + 期望。

    `state` 相对本数据集版本的 `states/`；`matrix_row` 是 PLAN_mcp_servers 附录 A
    的行号（覆盖表按它聚合）；`basis` 写期望的依据（地图 / 规则出处），给审用例的人看。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    matrix_row: int | None = Field(default=None, ge=2, le=15)
    script: str
    args: dict[str, str | int] = Field(default_factory=dict)
    state: str
    pre: tuple[str, ...] = ()
    expect: ScriptExpect
    basis: str
