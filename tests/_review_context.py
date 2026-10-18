"""旧复核席行为测试统一使用的必填随问快照。"""

from pokemon_agent.brain import Goal
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext


def review_context(run_id: str = "r1", episode_id: str = "r1-ep1") -> ReviewContext:
    """构造一张已提供但尚无条目的表，不为生产请求提供缺省快照。"""
    is_run = episode_id == run_id
    return ReviewContext(
        layer="run" if is_run else "episode",
        run_id=run_id,
        episode_id=episode_id,
        brain_input=FromHarnessToBrainToolJudgeReq(goal=Goal(goal="测试目标", criteria="达成")),
        goals=[] if is_run else None,
        tasks=None if is_run else [],
        step=1,
        fail_streak=0,
    )
