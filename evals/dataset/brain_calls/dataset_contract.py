"""五类测评数据契约；输入、独立评分依据与旧模型答案三者分离。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeTaskReq,
)

REQUESTS: dict[str, type[BaseModel]] = {
    "plan": FromHarnessToBrainToolPlanOnceReq,
    "decompose": FromHarnessToBrainToolDecomposeReq,
    "choose": FromHarnessToBrainToolChooseOnceReq,
    "judge": FromHarnessToBrainToolJudgeReq,
    "summarize": FromHarnessToBrainToolSummarizeReq,
    "summarize_task": FromHarnessToBrainToolSummarizeTaskReq,
    "summarize_run": FromHarnessToBrainToolSummarizeRunReq,
}
FAMILIES = {
    "plan": "plan",
    "decompose": "decompose",
    "choose": "choose",
    "judge": "judge",
    "summarize": "summary",
    "summarize_task": "summary",
    "summarize_run": "summary",
}
Family = Literal["judge", "plan", "decompose", "choose", "summary"]
Layer = Literal["run", "episode", "task"]


class Source(BaseModel):
    """来源只作审计，不作为待测模型的额外可见输入。"""

    sample_id: str
    request_file: str
    request_sha256: str
    request_canonical_sha256: str
    baseline_file: str | None
    baseline_sha256: str | None
    trace_uuids: list[str]
    meta: dict[str, str | int]
    elapsed_s: float | None
    baseline_status: Literal["success", "failure", "pending"]


class InputCase(BaseModel):
    """仅 request 送入原生产 Port；其余均为数据目录索引和评分元信息。"""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    family: Family
    layer: Layer
    method: str
    request: SerializeAsAny[BaseModel]
    source: Source

    @model_validator(mode="before")
    @classmethod
    def parse_production_request(cls, value: object) -> object:
        """JSON 重读时按原方法的精确契约解析，不用字段相似度猜类型。"""
        if isinstance(value, dict) and isinstance(value.get("request"), dict):
            value = dict(value)
            value["request"] = REQUESTS[value["method"]].model_validate(value["request"])
        return value


class Criterion(BaseModel):
    """有据可核的评分要求；不是被采集模型给出的参考答案。"""

    name: str
    instruction: str
    evidence: list[str]
    mandatory: bool = True


class ReferenceCase(BaseModel):
    """确定性标签仅在独立机械规则适用时给；开放任务使用源证据 rubric。"""

    case_id: str
    evaluation: Literal["mechanical", "action_set", "source_grounded_rubric"]
    achieved: bool | None = None
    check_id: str | None = None
    criteria: list[Criterion] = Field(min_length=1)
    constraints: dict[str, object]
    evidence: list[str]
    label_source: Literal["mechanical", "source_contract", "history_adjudicated"] = (
        "source_contract"
    )
    mechanical_reason: str = ""


class DatasetManifest(BaseModel):
    """文件字节指纹、类型和实际覆盖；不把未完成调用或 rubric 冒称人工 gold。"""

    version: str
    family: Family
    cases: int
    layers: dict[str, int]
    baseline_status: dict[str, int]
    mechanical_labels: int
    action_set_labels: int
    rubric_cases: int
    files_sha256: dict[str, str]
    source_head: str
    source_code_sha256: str
    schema_hash: str
    limitations: list[str]
