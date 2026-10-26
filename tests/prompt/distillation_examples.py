"""三层蒸馏的离线全文原料与旧版本注册表。"""

import json
from pathlib import Path

from pokemon_agent.prompt import (
    PromptGateway,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
)

from .layout_examples import details_data, observation_data, plan_data, task_data

Material = SummarizeTaskParams | SummarizeParams | SummarizeRunParams
OLD_VERSIONS = {"summarize_task": "v7", "summarize": "v6", "summarize_run": "v3"}
NEW_VERSIONS = {"summarize_task": "v8", "summarize": "v7", "summarize_run": "v6"}


def task_example() -> SummarizeTaskParams:
    """相邻动作共享一帧，先后顺序与完整对话均可核对。"""
    before = observation_data()
    after = {**before, "step": 3, "facts": {"overlay": "dialog", "dialog_text": "完整对话末句。"}}
    entries = [
        {
            "episode_id": "e",
            "task_id": "t",
            "step": 0,
            "before": before,
            "after": after,
            "action": "a",
            "before_frame": "A",
            "after_frame": "B",
        },
        {
            "episode_id": "e",
            "task_id": "t",
            "step": 1,
            "before": after,
            "after": before,
            "action": "b",
            "before_frame": "B",
            "after_frame": "C",
        },
    ]
    return SummarizeTaskParams.model_validate(
        {
            "goal": "读取招牌",
            "task_id": "t",
            "entries": entries,
            "termination": "goal_done",
            "success": True,
            "judge_reason": "完整判定依据。",
            "steps_used": 2,
            "max_steps": 5,
        }
    )


def episode_example() -> SummarizeParams:
    """两条 task 的首末图有重复边界，摘要及经验全文必须保留。"""
    first = {**task_data(), "first_frame": "A", "last_frame": "B"}
    second = {
        **first,
        "task_id": "t2",
        "total_acts": 4,
        "summary": "第二任务首句。\n第二任务全文末句。",
        "first_frame": "B",
        "last_frame": "C",
        "reason": "任务决定性依据全文。",
        "reusable_patterns": ["任务完整经验"],
        "failure_points": ["任务完整教训"],
    }
    return SummarizeParams.model_validate(
        {
            "goal": "读取招牌",
            "entries": [first, second],
            "termination": "goal_done",
            "success": True,
            "judge_reason": "完整判定依据。",
            "steps": 2,
            "max_steps": 4,
        }
    )


def run_example() -> SummarizeRunParams:
    """机器成功与人审最终推翻同时出现，不能丢失两者的差异。"""
    first = {**details_data()[0], "termination": "goal_done", "first_frame": "A", "last_frame": "B"}
    second = {
        **first,
        "episode_id": "e2",
        "summary": "第二局首句。\n第二局全文末句。",
        "first_frame": "B",
        "last_frame": "C",
        "reason": "局决定性依据全文。",
        "reusable_patterns": ["局完整经验"],
        "failure_points": ["局完整教训"],
    }
    goals = plan_data()
    goals[0].update(status="failed", note="人审推翻的完整理由。", overturned=True)
    return SummarizeRunParams.model_validate(
        {
            "run_goal": "读取招牌",
            "goals": goals,
            "episode_memories": [first, second],
            "termination": "budget_exhausted",
            "judge_reason": "完整判定依据。",
            "episodes": 2,
            "succeeded": 1,
            "acts_used": 7,
            "max_episodes": 3,
        }
    )


def examples() -> dict[str, Material]:
    """通过公开任务 Params 构造可独立渲染的三个样例。"""
    return {
        "summarize_task": task_example(),
        "summarize": episode_example(),
        "summarize_run": run_example(),
    }


def old_gateway(directory: Path) -> PromptGateway:
    """旧版固定 v7/v6/v3；活动 registry 不改动。"""
    source = Path(__file__).resolve().parents[2] / "pokemon_agent/prompt/registry.json"
    data = json.loads(source.read_bytes())
    for task, version in OLD_VERSIONS.items():
        data["tasks"][task]["active"] = version
    path = directory / "summarize-old-registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return PromptGateway(path)
