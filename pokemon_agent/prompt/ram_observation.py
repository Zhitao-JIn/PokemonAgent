"""判定模板消费的 RAM 观测文字素材，不依赖 world 或 harness。"""

from pydantic import BaseModel, ConfigDict, Field


class RamObservationRecord(BaseModel):
    """tool 已校验并序列化的单帧读数及可追溯来源。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    source: str
    episode_id: str
    task_id: str
    step: int
    observed_at: float
    sequence: int
    ram_json: str = Field(min_length=1)
