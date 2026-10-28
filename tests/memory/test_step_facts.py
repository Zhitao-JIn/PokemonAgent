"""事实按逐键观察顺序产生，保留重复与来源。"""

from pokemon_agent.memory.facts import task_facts
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory


def test_facts_preserve_all_observed_changes_and_sources() -> None:
    entries = []
    for step in range(40):
        before = {"step": step, "facts": {"dialog_text": "旧"}}
        after = {"step": step + 1, "facts": {"dialog_text": "旧"}}
        middle = {
            "step": step + 1,
            "place": {"map_id": 1, "x": 1, "y": 2},
            "facing": "up",
            "scene": "walk",
            "overlay": "dialog",
            "dialog_text": "重复",
        }
        entries.append(
            ActMemory.model_validate(
                {
                    "before": before,
                    "after": after,
                    "observations": [middle],
                    "action": "a",
                    "step": step,
                    "task_id": "t",
                    "episode_id": "e",
                }
            )
        )

    facts = task_facts(entries, "t", "e")

    repeated = [fact for fact in facts if fact.kind == "dialog_line" and fact.text == "重复"]
    assert len(repeated) == 40
    assert [fact.step for fact in repeated] == list(range(1, 41))
    assert all(fact.task_id == "t" and fact.episode_id == "e" for fact in facts)
    assert "facts" not in EpisodeMemory.model_fields
    assert "facts" not in RunMemory.model_fields
