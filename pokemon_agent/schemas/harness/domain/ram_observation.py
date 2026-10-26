"""一条供 run 判定使用的已落盘 RAM 观测；不携带图片或模型结论。"""

from pydantic import BaseModel, ConfigDict, Field

from pokemon_agent.world import RamReadout


class RamObservation(BaseModel):
    """保留观测时间、来源与原始读数，供 tool 层转换为模型文字素材。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    source: str
    episode_id: str
    task_id: str
    step: int
    observed_at: float
    sequence: int
    ram: RamReadout
