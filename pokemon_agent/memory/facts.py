"""从相邻观察机械摘取带来源的事实。"""

from collections.abc import Sequence

from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.schemas.memory.datastore.fact import Fact

from .changes import changes


def task_facts(entries: Sequence[ActMemory], task_id: str, episode_id: str) -> list[Fact]:
    """按原始顺序保留每次相邻观察的全部差异及双重步号。"""
    result: list[Fact] = []
    for entry in entries:
        observations = entry.observations
        frames = [entry.before, *observations, entry.after]
        for index, (before, after) in enumerate(zip(frames, frames[1:], strict=False)):
            sub = observations[index].step if index < len(observations) else 0
            for change in changes(before, after):
                result.append(
                    Fact(
                        step=entry.after.step,
                        sub=sub,
                        kind=change.kind,
                        place=change.place.model_dump() if change.place is not None else None,
                        object=change.object.model_dump() if change.object is not None else None,
                        text=change.text,
                        task_id=task_id,
                        episode_id=episode_id,
                    )
                )
    return result


def task_step_range(entries: Sequence[ActMemory]) -> list[str]:
    """Return one inclusive局内步号 interval for a non-empty task history."""
    if not entries:
        return []
    return [f"{entries[0].before.step}-{entries[-1].after.step}"]


__all__ = ["Fact", "task_facts", "task_step_range"]
