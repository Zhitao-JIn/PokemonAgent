"""已有 object 事件命中完整 MemoryTool 门面时，两种传输都返回字符串 content。"""

import json

import pytest
from pydantic import TypeAdapter
from test_mcp_memory_e2e import (
    _act_payload,
    _knowledge_payload,
    _object_payload,
    _task_payload,
)
from test_memory_admin_parity import Embedder, Reranker
from test_memory_admin_parity import remote as remote

from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)
from pokemon_agent.schemas.memory import ObjectFactEvent


def tools(tmp_path, remote):
    return [MemoryTool(Embedder(), Reranker(), memory_root=tmp_path / "local"), remote[3]]


@pytest.mark.parametrize("conditions", [{"place": "12:13:8"}, {"map_id": "12"}])
def test_object_content_round_trips_through_both_complete_port_implementations(
    tmp_path, remote, conditions
):
    records = [{"kind": "object", "payload": _object_payload(step)} for step in (1, 2)]
    results = []
    for tool in tools(tmp_path, remote):
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=records))

        response = tool.recall(FromHarnessToMemoryToolRecallReq(query="", conditions=conditions))

        assert len(response.items) == 2
        for item in response.items:
            expected = (
                TypeAdapter(ObjectFactEvent).validate_python(item.payload).model_dump(mode="json")
            )
            assert item.kind == "object"
            assert isinstance(item.content, str)
            assert json.loads(item.content) == expected
            assert "你好" in item.content
        results.append([(item.content, item.payload) for item in response.items])
    assert results[0] == results[1]


def test_mixed_recall_items_all_satisfy_the_port_in_both_modes(tmp_path, remote):
    records = [
        {"kind": "act", "payload": _act_payload()},
        {"kind": "task", "payload": _task_payload()},
        {"kind": "object", "payload": _object_payload()},
        {"kind": "knowledge", "payload": _knowledge_payload()},
    ]
    results = []
    for tool in tools(tmp_path, remote):
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=records))

        response = tool.recall(
            FromHarnessToMemoryToolRecallReq(
                query="草丛",
                conditions={"episode_id": "e1", "place": "12:13:8", "map_id": "12"},
                limit=20,
            )
        )

        assert {item.kind for item in response.items} == {"act", "task", "object", "knowledge"}
        assert all(isinstance(item.content, str) for item in response.items)
        results.append([(item.kind, item.content, item.payload) for item in response.items])
    assert results[0] == results[1]
