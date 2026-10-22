"""原始事件经过检索、信封与网关，文字只在版本内生成。"""

from types import SimpleNamespace

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import call_policy
from pydantic import JsonValue, TypeAdapter

from pokemon_agent.brain import Brain, Goal, Task
from pokemon_agent.direct.brain_tool import Decomposer
from pokemon_agent.direct.prompts import decompose
from pokemon_agent.direct.prompts.object_render import render_object_events
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
        status="ok",
        scene=TaskScene.WALK,
        place=PlaceInWorld(map_id=1, x=-2, y=3),
        facts=Facts(where="全局坐标 地图1 x=-2 y=3"),
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
    assert not merged.object_semantic_memory
    assert not (merged.observation.facts.model_extra or {})
    assert memory.requests[0].conditions == {"run_id": "run", "map_id": "1"}
    assert trace.requests[0].refs == [e.place.key for e in events[:3]]
    old_obs = obs.model_copy(
        update={
            "facts": obs.facts.model_copy(
                update={"known_objects": render_object_events(events[:3])}
            )
        }
    )
    old_req = req.model_copy(update={"observation": old_obs})
    assert provider.requests[0].prompt == decompose.build_prompt(old_req)
    assert response.calls[0].payload["prompt_task"] == "decompose"


@pytest.mark.parametrize("outcome", ["dialog", "warp", "still"])
def test_text_adapter_restores_only_information_present_in_the_text(outcome: str) -> None:
    events = [event(2, outcome), event(1, "still")]
    text = render_object_events(events)
    raw = restore_object_events(text)
    obs = TaskObservation(step=4, status="ok", scene=TaskScene.WALK)
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
    expected = decompose.build_prompt(
        FromHarnessToBrainToolDecomposeReq(
            goal=Goal(goal="g", criteria="c"),
            observation=obs.model_copy(
                update={"facts": obs.facts.model_copy(update={"known_objects": text})}
            ),
            max_tasks=3,
        )
    )
    assert actual.text == expected
