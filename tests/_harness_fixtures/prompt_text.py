"""通过公共网关读取素材，测试不依赖 world/memory 的旧排版方法。"""

from pydantic import BaseModel

from pokemon_agent.prompt import (
    DecomposeParams,
    JudgeParams,
    PromptGateway,
    RunPlanParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory, TaskMemory


def index_text(memory: EpisodeMemory | RunMemory | TaskMemory) -> str:
    """经任务素材出口取得背景索引。"""
    gateway = PromptGateway(None)
    data = memory.model_dump(mode="json")
    if isinstance(memory, RunMemory):
        params = RunPlanParams.model_validate(
            {
                "run_goal": {"goal": "g", "criteria": "c"},
                "run_id": "r",
                "run_index": [data],
                "max_push": 1,
            }
        )
        return gateway.render_history("run_plan", params)[-1]
    if isinstance(memory, EpisodeMemory):
        params = DecomposeParams.model_validate(
            {
                "goal": {"goal": "g", "criteria": "c"},
                "observation": {"step": 0, "facts": {"overlay": "none"}},
                "episode_index": [data],
                "max_tasks": 1,
                "terrain_meanings": {},
            }
        )
        return next(
            line for line in gateway.render_history("decompose", params) if line.startswith("- ")
        )
    params = JudgeParams.model_validate(
        {"goal": {"goal": "g", "criteria": "c"}, "task_index": [data]}
    )
    return gateway.render_history("judge_success", params)[-1].splitlines()[-1]


def record_text(memory: ActMemory | TaskMemory | EpisodeMemory) -> str:
    """经任务素材出口取得单条完整正文。"""
    data = memory.model_dump(mode="json")
    gateway = PromptGateway(None)
    if isinstance(memory, EpisodeMemory):
        params = SummarizeRunParams.model_validate(
            {
                "run_goal": "g",
                "goals": [],
                "episode_memories": [data],
                "termination": "",
                "judge_reason": "",
                "episodes": 1,
                "succeeded": 0,
                "acts_used": 0,
                "max_episodes": 1,
            }
        )
        return gateway.render_history("summarize_run", params)[0]
    return gateway.render_history(
        "verify", VerifyParams.model_validate({"goal": "g", "entries": [data]})
    )[0]


def observation_text(observation: BaseModel) -> str:
    """经判定任务取完整当前观测文本。"""
    params = JudgeParams.model_validate(
        {"goal": {"goal": "g", "criteria": "c"}, "observation": observation.model_dump(mode="json")}
    )
    return (
        PromptGateway(None)
        .render_history("judge_success", params)[-1]
        .removeprefix("## 当前画面\n")
    )


def sequence_text(entries: list[ActMemory]) -> list[str]:
    """经task蒸馏取相邻快照去重后的素材列表。"""
    params = SummarizeTaskParams.model_validate(
        {
            "goal": "g",
            "task_id": "t",
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "verdicts": [],
            "termination": "",
            "success": False,
            "steps_used": len(entries),
            "max_steps": max(1, len(entries)),
        }
    )
    return [
        block.split("\n", 1)[1]
        for block in PromptGateway(None).render_history("summarize_task", params)
    ]
