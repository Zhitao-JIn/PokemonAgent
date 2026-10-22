"""无模型和网关依赖的记忆组装，保留快照及全部来源字段。"""

import json
from pathlib import Path

import pytest

from pokemon_agent.brain import Action, ActionSegment, Brain, BrainPort
from pokemon_agent.direct.brain_tool import Reflector
from pokemon_agent.schemas.harness import FromHarnessToBrainToolReflectReq
from pokemon_agent.schemas.memory import SNAPSHOT_BLIND, ActMemory
from pokemon_agent.world import TaskObservation

CASES = sorted((Path(__file__).parent / "golden/decide_action").glob("*.req.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
def test_reflector_preserves_the_full_record_without_a_brain(path: Path) -> None:
    observation = TaskObservation.model_validate(json.loads(path.read_bytes())["request"]["obs"])
    observation.facts.known_objects = "检索物体"
    observation.facts.knowledge = "检索知识"
    after = observation.model_copy(update={"step": observation.step + 1})
    req = FromHarnessToBrainToolReflectReq(
        before=observation,
        after=after,
        action=Action(sequence=[ActionSegment(name="up")]),
        episode_id="ep",
        step=7,
        result="原样结果",
    )
    original = req.model_dump_json()
    expected_snapshots = []
    for obs in (observation, after):
        raw = obs.model_dump(mode="json")
        raw["facts"] = {
            key: value for key, value in raw["facts"].items() if key not in SNAPSHOT_BLIND
        }
        expected_snapshots.append(ActMemory.Observation.model_validate(raw).model_dump(mode="json"))
    reflector = Reflector()

    result = reflector.reflect(req).entry.model_dump(mode="json")

    assert result == {
        "before": expected_snapshots[0],
        "after": expected_snapshots[1],
        "action": "up",
        "result": "原样结果",
        "step": 7,
        "episode_id": "ep",
        "task_id": "",
        "run_id": "",
        "before_frame": None,
        "after_frame": None,
    }
    assert req.model_dump_json() == original
    assert vars(reflector) == {}
    assert not hasattr(Brain, "reflect")
    assert not hasattr(BrainPort, "reflect")
