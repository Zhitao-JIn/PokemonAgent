"""三层审查的随问快照，以及大脑输入记忆帧的只读提取。"""

from typing import Literal, Self

from pydantic import BaseModel, model_validator

from pokemon_agent.schemas.harness.communication.FromHarnessToBrainToolDecomposeReq import (
    FromHarnessToBrainToolDecomposeReq,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToBrainToolJudgeReq import (
    FromHarnessToBrainToolJudgeReq,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToBrainToolPlanOnceReq import (
    FromHarnessToBrainToolPlanOnceReq,
)

from .goal_entry import GoalEntry
from .task_entry import TaskEntry

BrainInput = (
    FromHarnessToBrainToolPlanOnceReq
    | FromHarnessToBrainToolDecomposeReq
    | FromHarnessToBrainToolJudgeReq
)


class ReviewContext(BaseModel):
    """保留当次大脑请求原对象；表的归属互斥，首轮允许尚未填行的空表。"""

    layer: Literal["run", "episode", "task"]
    run_id: str
    episode_id: str
    task_id: str | None = None
    brain_input: BrainInput
    goals: list[GoalEntry] | None = None
    tasks: list[TaskEntry] | None = None
    step: int
    fail_streak: int

    @model_validator(mode="after")
    def validate_layer_tables(self) -> Self:
        """run 必须提供目标表，episode 必须提供任务表；另一张表必须为 None。"""
        if self.layer == "run" and (self.goals is None or self.tasks is not None):
            raise ValueError("run context requires goals and forbids tasks")
        if self.layer == "episode" and (self.tasks is None or self.goals is not None):
            raise ValueError("episode context requires tasks and forbids goals")
        if self.layer == "task" and (
            self.goals is not None
            or self.tasks is not None
            or not self.task_id
            or not isinstance(self.brain_input, FromHarnessToBrainToolJudgeReq)
        ):
            raise ValueError("task context requires task_id and JudgeReq and forbids tables")
        return self


def frames_of(brain_input: BrainInput) -> list[tuple[str, str]]:
    """按请求内详情顺序取首末帧，跳过缺帧并按原字符串去重；不限制张数。

    调用方提供本次实际大脑请求；承诺返回非空、互不重复的帧字符串及首次出现的来源标签。
    本函数不读取外部状态；task 层逐条提取 history 的前后帧。
    """
    if isinstance(brain_input, FromHarnessToBrainToolPlanOnceReq):
        memories = brain_input.details
    elif isinstance(brain_input, FromHarnessToBrainToolDecomposeReq):
        memories = brain_input.task_memories
    else:
        memories = [*brain_input.episode_memories, *brain_input.task_memories]
    candidates: list[tuple[str, str | None]] = []
    for memory in memories:
        identifier = memory.task_id if hasattr(memory, "task_id") else memory.episode_id
        for label, frame in (("首帧", memory.first_frame), ("末帧", memory.last_frame)):
            candidates.append((f"{identifier} {label}", frame))
    if isinstance(brain_input, FromHarnessToBrainToolJudgeReq):
        for memory in brain_input.history:
            for label, frame in (("前帧", memory.before_frame), ("后帧", memory.after_frame)):
                candidates.append((f"{memory.task_id} 第 {memory.step} 键{label}", frame))
    frames: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, frame in candidates:
        if frame and frame not in seen:
            frames.append((label, frame))
            seen.add(frame)
    assert all(frame for _, frame in frames), "frames_of returned a missing frame"
    assert len(frames) == len({frame for _, frame in frames}), "frames_of returned duplicates"
    return frames
