"""harness → run 蒸馏门面的最终素材与来源章。"""

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.goal_entry import GoalEntry
from pokemon_agent.schemas.harness.domain.termination import Settled, Termination
from pokemon_agent.schemas.memory import EpisodeMemory


class FromHarnessToBrainToolSummarizeRunReq(Settled, BaseModel):
    """正常收尾的 run 蒸馏请求；来源章由 harness 给定。"""

    run_id: str
    run_goal: str
    goals: list[GoalEntry]
    episode_memories: list[EpisodeMemory] = Field(min_length=1)
    termination: Termination
    judge_reason: str
    episodes: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    acts_used: int = Field(ge=0)
    max_episodes: int = Field(ge=1)
