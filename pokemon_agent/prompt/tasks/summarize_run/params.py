"""summarize_run 的独立原料契约。"""

from pydantic import BaseModel

from ...records import EpisodeRecord, GoalRecord


class SummarizeRunParams(BaseModel):
    run_goal: str
    goals: list[GoalRecord]
    episode_memories: list[EpisodeRecord]
    termination: str
    judge_reason: str
    episodes: int
    succeeded: int
    acts_used: int
    max_episodes: int
