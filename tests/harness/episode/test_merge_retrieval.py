"""检索汇合不再消费旧存档的物体文本，原始事件仍走独立字段。"""

from types import SimpleNamespace

from pokemon_agent.brain import Task
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.perceive.merge_retrieval import merge_retrieval
from pokemon_agent.world import Facts, PlaceInWorld, TaskObservation, TaskScene


def state() -> EpisodeRunState:
    return EpisodeRunState(
        run_id="r",
        run_goal="g",
        episode_id="e",
        goal=Task(task_id="t", goal="g", success_criteria="c", max_steps=1),
        ep_ctx=EpisodeContext(
            observation=TaskObservation(
                step=0,
                scene=TaskScene.WALK,
                place=PlaceInWorld(map_id=12, x=16, y=12),
                facts=Facts(overlay=Facts.Overlay.NONE),
            )
        ),
    )


def test_merge_preserves_the_structured_context() -> None:
    original = state()
    result = merge_retrieval(original, SimpleNamespace())
    assert result["ep_ctx"] is original.ep_ctx
    assert result["ep_ctx"].observation.place.x == 16


def test_removed_semantic_retrieval_is_not_a_context_field() -> None:
    assert "semantic_memory" not in EpisodeContext.model_fields
    original = state()
    assert not original.ep_ctx.observation.facts.model_extra


def test_dynamic_snapshot_blind_fields_can_still_be_removed() -> None:
    facts = Facts(overlay=Facts.Overlay.NONE, transient_retrieval="retrieved")
    clean = facts.exclude(frozenset({"transient_retrieval"}))
    assert not clean.model_extra
    assert clean.overlay == facts.overlay
