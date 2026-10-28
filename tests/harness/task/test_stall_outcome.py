"""结构化脚本结局驱动停摆签名。"""

from pokemon_agent.brain import Action, ScriptCall
from pokemon_agent.harness.task.perceive.detect_stall import compute_stall
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import TaskObservation, TaskScene


def test_failed_scripts_with_the_same_code_keep_the_same_signature() -> None:
    obs = TaskObservation(step=0, scene=TaskScene.WALK)
    first = Action(script=ScriptCall(name="walk_to", args={"x": 1, "y": 2}))
    second = Action(script=ScriptCall(name="walk_to", args={"x": 4, "y": 5}))
    failed = ActMemory.ScriptOutcome(code="blocked", ok=False, reason="blocked")

    key, count = compute_stall(obs, first, None, 0, failed)
    next_key, next_count = compute_stall(obs, second, key, count, failed)

    assert next_key == key and next_count == 2


def test_successful_scripts_with_different_summaries_have_different_signatures() -> None:
    obs = TaskObservation(step=0, scene=TaskScene.WALK)
    action = Action(script=ScriptCall(name="walk_to", args={"x": 1, "y": 2}))
    first = ActMemory.ScriptOutcome(code="ok", ok=True, summary="HP 20")
    second = ActMemory.ScriptOutcome(code="ok", ok=True, summary="HP 10")

    key, count = compute_stall(obs, action, None, 0, first)
    next_key, next_count = compute_stall(obs, action, key, count, second)
    same_key, same_count = compute_stall(obs, action, next_key, next_count, second)

    assert next_key != key and next_count == 1
    assert same_key == next_key and same_count == 2
