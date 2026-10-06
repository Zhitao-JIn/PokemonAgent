"""冻结记忆库与查询相关性标注，存储与检索共用一次写入。"""

from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness import FromHarnessToMemoryToolMemorizeRecord


class FrozenRecord(BaseModel):
    """记录身份由数据集给出，落库 uuid 在本次运行中映射。"""

    record_id: str
    record: FromHarnessToMemoryToolMemorizeRecord
    query: str
    expected_content: str
    conditions: dict[str, str] = Field(default_factory=dict)


class Query(BaseModel):
    """相关性标注引用 record_id，不能引用当次随机 uuid。"""

    query_id: str
    text: str
    relevant: list[str] = Field(min_length=1)
    conditions: dict[str, str] = Field(default_factory=dict)


class MemoryDataset(BaseModel):
    """一份冻结库及其查询。"""

    records: list[FrozenRecord] = Field(min_length=1)
    queries: list[Query] = Field(min_length=1)


class MemoryRun(StoreModel):
    """一次写入、逐条读回、全部检索的交接面。"""

    storage_problems: list[str] = Field(default_factory=list)
    retrieved: dict[str, list[str]] = Field(default_factory=dict)
