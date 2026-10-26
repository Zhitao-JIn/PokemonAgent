"""从唯一账本选取本执行线最近五次 RAM 观测，不读取或改变模拟器。"""

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.schemas.harness import TraceEvent, TraceKind
from pokemon_agent.schemas.harness.domain.ram_observation import RamObservation
from pokemon_agent.world import RamReadout


class _Meta(BaseModel):
    """本函数消费的观测来源字段。"""

    run_id: str
    branch: str
    source: str
    episode_id: str
    task_id: str
    step: int


class _Content(BaseModel):
    """观测事件中需要传给判定器的读数。"""

    ram: RamReadout | None = None


def recent_ram_observations(
    events: Sequence[TraceEvent], *, run_id: str, branch: str
) -> list[RamObservation]:
    """返回按时间排列的最近五条有效读数；不足五条全取，没有则返回空表。

    前置条件：事件符合 trace 契约。损坏的事件或 RAM 数据显式校验失败，不补造读数。
    不同 run/branch、非观测事件和合法的无 RAM 历史事件不会进入结果。
    """
    observations: list[RamObservation] = []
    for event in sorted(events, key=lambda entry: (entry.ended_at, entry.seq)):
        if event.kind != TraceKind.SENSE_FRAME:
            continue
        meta = _Meta.model_validate_json(event.meta)
        if meta.run_id != run_id or meta.branch != branch:
            continue
        content = _Content.model_validate_json(event.content)
        if content.ram is None:
            continue
        observations.append(
            RamObservation(
                event_id=event.uuid,
                source=meta.source,
                episode_id=meta.episode_id,
                task_id=meta.task_id,
                step=meta.step,
                observed_at=event.ended_at,
                sequence=event.seq,
                ram=content.ram,
            )
        )
    return observations[-5:]
