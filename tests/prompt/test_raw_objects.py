"""原始事件经过检索、信封与网关，文字只在版本内生成。"""

from types import SimpleNamespace

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import call_policy
from pydantic import JsonValue, TypeAdapter

from pokemon_agent.brain import Brain, Goal, Task
from pokemon_agent.direct.brain_tool import Decomposer
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.perceive.merge_retrieval import merge_retrieval
from pokemon_agent.harness.episode.perceive.retrieve_object_semantic_memory import (
    retrieve_object_semantic_memory,
)
from pokemon_agent.prompt import DecomposeParams, PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.schemas.memory import ObjectFactEvent
from pokemon_agent.world import TERRAIN_MEANING, Facts, PlaceInWorld, TaskObservation, TaskScene

from .legacy_adapter import restore_object_events


def event(step: int, outcome: str) -> ObjectFactEvent:
    raw: dict[str, JsonValue] = {
        "episode_id": "ep",
        "run_id": "run",
        "step": step,
        "actor_place": {"map_id": 1, "x": -2, "y": 3},
        "place": {"map_id": 1, "x": -2, "y": 4},
        "button": "a",
        "object_kind": "人",
        "outcome": outcome,
    }
    if outcome == "dialog":
        raw["text"] = '你好"朋友"\n下一行'
    elif outcome == "warp":
        raw["map_id"] = 9
    return TypeAdapter(ObjectFactEvent).validate_python(raw)


class Memory:
    def __init__(self, events: list[ObjectFactEvent]) -> None:
        self.events = events
        self.requests: list[FromHarnessToMemoryToolRecallReq] = []

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        self.requests.append(req)
        return FromHarnessToMemoryToolRecallResp.model_validate(
            {
                "items": [
                    {"kind": "object", "uuid": str(i), "payload": e.model_dump(mode="json")}
                    for i, e in enumerate(self.events)
                ]
            }
        )


class Trace:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToTraceToolAppendReq] = []

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        self.requests.append(req)


def test_retrieved_events_keep_filter_trace_and_old_model_input() -> None:
    events = [event(3, "dialog"), event(1, "warp"), event(2, "still"), event(4, "still")]
    obs = TaskObservation(
        step=4,
        scene=TaskScene.WALK,
        place=PlaceInWorld(map_id=1, x=-2, y=3),
        facts=Facts(overlay=Facts.Overlay.NONE),
    )
    state = EpisodeRunState(
        run_id="run",
        run_goal="总目标",
        episode_id="ep",
        total_acts=4,
        goal=Task(task_id="g", goal="交谈", success_criteria="结束", max_steps=3),
        ep_ctx=EpisodeContext(observation=obs),
    )
    memory, trace = Memory(events), Trace()
    runtime = SimpleNamespace(context=SimpleNamespace(memory=memory, trace=trace))
    provider = ScriptedLLM(text_reply('{"new_items":[],"execution_order":null,"why":"保留"}'))
    gateway = PromptGateway(None)
    capability = Decomposer(
        Brain(plan_llm=provider), policy=call_policy(max_attempts=1), prompt_gateway=gateway
    )

    context = retrieve_object_semantic_memory(state, runtime)["ep_ctx"]
    state.ep_ctx = context
    merged = merge_retrieval(state, runtime)["ep_ctx"]
    req = FromHarnessToBrainToolDecomposeReq(
        goal=Goal(goal="交谈", criteria="结束"),
        observation=merged.observation,
        known_objects=merged.object_semantic_events,
        max_tasks=3,
    )
    response = capability.decompose(req)

    assert merged.object_semantic_events == events[:3]
    assert "object_semantic_memory" not in type(merged).model_fields
    assert not (merged.observation.facts.model_extra or {})
    assert memory.requests[0].conditions == {"run_id": "run", "map_id": "1"}
    assert trace.requests[0].refs == [e.place.key for e in events[:3]]
    prompt = provider.requests[0].prompt
    lines = [
        "step1 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：进入新地图9",
        "step2 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：无效果",
        'step3 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：对话"你好"朋友"',
        '下一行"',
    ]
    positions = [prompt.index(line) for line in lines]
    assert positions == sorted(positions)
    assert "step4 站在" not in prompt
    assert "ep step" not in prompt
    assert response.calls[0].payload["prompt_task"] == "decompose"


@pytest.mark.parametrize("outcome", ["dialog", "warp", "still"])
def test_text_adapter_restores_only_information_present_in_the_text(outcome: str) -> None:
    result = {
        "dialog": '对话"你好"朋友"\n下一行"',
        "warp": "进入新地图9",
        "still": "无效果",
    }[outcome]
    text = (
        "ep step1 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：无效果\n"
        f"ep step2 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：{result}"
    )
    raw = restore_object_events(text)
    obs = TaskObservation(facts={"overlay": "none"}, step=4, scene=TaskScene.WALK)
    params = DecomposeParams.model_validate(
        {
            "goal": {"goal": "g", "criteria": "c"},
            "observation": obs.model_dump(mode="json"),
            "max_tasks": 3,
            "terrain_meanings": TERRAIN_MEANING,
            "known_objects": raw,
        }
    )

    actual = PromptGateway(None).render("decompose", params)

    assert "run_id" not in raw[0] and "map_id" not in raw[0]["actor_place"]
    for line in text.splitlines():
        assert line.removeprefix("ep ") in actual.text
    assert "ep step" not in actual.text
    assert actual.text.index("step1 站在") < actual.text.index("step2 站在")
