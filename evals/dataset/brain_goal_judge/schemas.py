"""目标完成判定数据集的版本化样本契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq

GoalFamily = Literal[
    "navigation",
    "interaction",
    "party_or_inventory",
    "battle_or_encounter",
    "other",
]
NegativeMode = Literal[
    "near_miss",
    "wrong_map_or_location",
    "wrong_dialogue_or_event",
    "required_state_missing",
    "other",
]
TruthMethod = Literal["mechanical", "history_adjudicated", "human"]


class JudgeCase(BaseModel):
    """跨版本共享的消费字段；标签由 scorer 消费，不进入 judge 请求。"""

    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(min_length=1)
    request: FromHarnessToBrainToolJudgeReq
    achieved: bool


class JudgeCaseV1(JudgeCase):
    """保留四条旧契约样本的核心数据形状。"""

    model_config = ConfigDict(extra="forbid")


class JudgeOrigin(BaseModel):
    """可定位到一条原始 task judge 调用的来源坐标。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step: int = Field(ge=0)
    trace_uuid: str = Field(min_length=1)


class JudgeEvidence(BaseModel):
    """一条独立标签证据的来源定位和可审阅摘要。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class JudgeCaseV2(JudgeCase):
    """带完整真值依据的扩展样本。"""

    model_config = ConfigDict(extra="forbid")

    goal_family: GoalFamily
    negative_mode: NegativeMode | None
    truth_method: TruthMethod
    check_id: str | None = None
    origin: JudgeOrigin
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: list[JudgeEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_truth_metadata(self) -> JudgeCaseV2:
        """标签类别、判定方式和独立证据必须匹配。"""
        if self.achieved and self.negative_mode is not None:
            raise ValueError("已达成样本的 negative_mode 必须为空")
        if not self.achieved and self.negative_mode is None:
            raise ValueError("未达成样本必须填写 negative_mode")
        if self.truth_method == "mechanical" and not self.check_id:
            raise ValueError("mechanical 真值必须填写 check_id")
        return self


__all__ = [
    "GoalFamily",
    "JudgeCase",
    "JudgeCaseV1",
    "JudgeCaseV2",
    "JudgeEvidence",
    "JudgeOrigin",
    "NegativeMode",
    "TruthMethod",
]
