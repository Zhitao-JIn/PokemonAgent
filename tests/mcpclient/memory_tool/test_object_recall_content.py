"""已有 object 事件命中完整 MemoryTool 门面时，MCP 返回字符串 content。"""

from typing import Any

import pytest
from _doubles.memory_server import remote as remote
from pydantic import TypeAdapter

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)
from pokemon_agent.schemas.memory import ActMemory, ObjectFactEvent, TaskMemory

RUN = "r1"
EP = "e1"


def _act_payload(step: int = 1) -> dict[str, Any]:
    obs = ActMemory.Observation(facts={"overlay": "none"}, step=step)
    return ActMemory(
        before=obs,
        action="up",
        after=obs,
        step=step,
        episode_id=EP,
        run_id=RUN,
        observations=[],
        outcome=None,
    ).model_dump()


def _task_payload(task_id: str = "t1") -> dict[str, Any]:
    return TaskMemory(
        run_id=RUN,
        episode_id=EP,
        task_id=task_id,
        goal="走到草丛",
        termination="goal_done",
        reason="到达",
        steps_used=3,
        total_acts=3,
        summary="沿空地向北走到草丛边。",
        quality_score=0.5,
        quality_rationale="常规移动。",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _object_payload(step: int = 1) -> dict[str, Any]:
    from pokemon_agent.schemas.memory.datastore.object_memory import ObjectDialogEvent

    place = ObjectDialogEvent.Place(map_id=12, x=13, y=8)
    return ObjectDialogEvent(
        outcome="dialog",
        episode_id=EP,
        step=step,
        run_id=RUN,
        place=place,
        actor_place=place,
        object_kind="人",
        button="a",
        text="你好。",
    ).model_dump()


def _knowledge_payload(
    topic: str = "草丛", text: str = "草丛里会遇到野生宝可梦。"
) -> dict[str, Any]:
    return {"topic": topic, "text": text, "source": f"{RUN}/{EP}", "run_id": RUN, "episode_id": EP}


@pytest.mark.parametrize("conditions", [{"place": "12:13:8"}, {"map_id": "12"}])
def test_object_content_round_trips_through_the_mcp_port(remote, conditions):
    """object 条目满足 MCP 端口模型：payload 经 `ObjectFactEvent` 校验、content 是 JSON 字符串。

    memory 侧的内容往返断言（content 与 payload 逐字段相等、"你好" 在正文里）已迁去
    `tests/memory/capability/` 用例 7/15，直调 `MemoryCapability`；这里只留 MCP 端口的形状。
    """
    records = [{"kind": "object", "payload": _object_payload(step)} for step in (1, 2)]
    _, tool = remote
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=records))

    response = tool.recall(FromHarnessToMemoryToolRecallReq(query="", conditions=conditions))

    assert len(response.items) == 2
    for item in response.items:
        TypeAdapter(ObjectFactEvent).validate_python(item.payload)
        assert item.kind == "object"
        assert isinstance(item.content, str)


def test_mixed_recall_items_all_satisfy_the_mcp_port(remote):
    records = [
        {"kind": "act", "payload": _act_payload()},
        {"kind": "task", "payload": _task_payload()},
        {"kind": "object", "payload": _object_payload()},
        {"kind": "knowledge", "payload": _knowledge_payload()},
    ]
    _, tool = remote
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
