"""知识 query 只使用结构特征与当前目标。"""

from pokemon_agent.harness.knowledge_query import build_knowledge_query
from pokemon_agent.world import Facts, PlaceInWorld, TaskObservation, TaskScene


def test_knowledge_query_uses_scene_overlay_map_and_goal_without_rendered_status() -> None:
    observation = TaskObservation(
        step=1,
        scene=TaskScene.DIALOG,
        place=PlaceInWorld(map_id=12, x=3, y=4),
        facts=Facts(overlay=Facts.Overlay.DIALOG),
    )

    query = build_knowledge_query(observation, "寻找入口")

    assert query == "scene:dialog overlay:dialog map:12 目标：寻找入口"
    assert "THIS_STATUS_MUST_NOT_ENTER_THE_QUERY" not in query
