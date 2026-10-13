"""冻结记录与相关性标签；每条记录和每次查询各组成一个用例。"""

import json
from pathlib import Path

from deepeval.test_case import LLMTestCase
from pydantic import BaseModel, Field

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory
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


DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v1"
__all__ = ["FrozenRecord", "MemoryDataset", "Query", "load"]


def load(version: str = DEFAULT_VERSION) -> list[MemoryDataset]:
    """返回类型化样本；冻结文件或契约错误抛 DatasetError。"""
    rows = read_models(
        version_directory(DATASET_DIR, version) / "dataset.json", MemoryDataset, json_lines=False
    )
    for dataset in rows:
        identities = {entry.record_id for entry in dataset.records}
        if len(identities) != len(dataset.records):
            raise DatasetError("record_id 不唯一")
        if not all(set(q.relevant) <= identities for q in dataset.queries):
            raise DatasetError("相关性标注引用未知记录")
    return rows


def build_cases(
    dataset: MemoryDataset, storage_problems: list[str], retrieved: dict[str, list[str]]
) -> list[LLMTestCase]:
    """使用 solver 的真实产物造用例；查询必须已全部执行。"""
    assert set(retrieved) == {query.query_id for query in dataset.queries}
    stores = [
        LLMTestCase(
            name=f"store:{entry.record_id}",
            input=entry.query,
            actual_output=json.dumps(
                {
                    "problems": [
                        problem
                        for problem in storage_problems
                        if problem.startswith(entry.record_id + ":")
                    ]
                },
                ensure_ascii=False,
            ),
            additional_metadata={"kind": "store"},
        )
        for entry in dataset.records
    ]
    queries = [
        LLMTestCase(
            name=f"query:{query.query_id}",
            input=query.text,
            actual_output=json.dumps(retrieved[query.query_id], ensure_ascii=False),
            expected_output=json.dumps(query.relevant, ensure_ascii=False),
            retrieval_context=retrieved[query.query_id],
            additional_metadata={"kind": "query"},
        )
        for query in dataset.queries
    ]
    return stores + queries
