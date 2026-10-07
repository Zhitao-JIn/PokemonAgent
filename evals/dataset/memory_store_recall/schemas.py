"""冻结样本的数据契约。"""

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
