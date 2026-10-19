"""三层 judge 冻结契约；原样保留上层 trace 的空 task_id。"""

from typing import Literal

from pydantic import Field, model_validator

from evals.dataset.brain_judge.schemas import JudgeCaseV2, JudgeOrigin


class JudgeOriginV3(JudgeOrigin):
    """同一模型尝试的原始 trace 标签，不能把上层空身份伪装成 task。"""

    task_id: str
    branch: str = Field(min_length=1)
    source: str = Field(min_length=1)


class JudgeCaseV3(JudgeCaseV2):
    """保留 V2 真值元数据，显式区分 run、episode、task 三层分母。"""

    layer: Literal["run", "episode", "task"]
    origin: JudgeOriginV3

    @model_validator(mode="after")
    def validate_layer_origin(self) -> "JudgeCaseV3":
        """task 必须有 task 身份；上层如实保留实际标签，不补造身份。"""
        if self.layer == "task" and not self.origin.task_id:
            raise ValueError("task judge needs task identity")
        return self
