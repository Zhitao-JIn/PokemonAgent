"""三个 plan 的离线原料，仅通过公开 Params 构造。"""

from pydantic import JsonValue

from pokemon_agent.prompt import DecideActionParams, DecomposeParams, RunPlanParams


def plan_data() -> list[dict[str, JsonValue]]:
    """完整的离线原料。"""
    return [{"task": {"task_id": "entry", "goal": "读取招牌", "success_criteria": "取得招牌文字"}}]


def details_data() -> list[dict[str, JsonValue]]:
    """完整的离线原料。"""
    return [
        {
            "episode_id": "e",
            "run_id": "r",
            "goal": "读取招牌",
            "steps": 1,
            "summary": "局首句。局全文包含完整招牌原文。",
            "quality_score": 0.5,
            "quality_rationale": "核验",
            "pointers": [],
            "index": {"headline": "", "keys": [], "evidence": []},
            "first_frame": "FRAME_FIRST",
            "last_frame": "FRAME_LAST",
        }
    ]


def run_index_data() -> list[dict[str, JsonValue]]:
    """完整的离线原料。"""
    return [
        {
            "run_id": "past",
            "run_goal": "读取招牌",
            "episodes": 1,
            "succeeded": 1,
            "summary": "背景首句。背景正文不作本层证据。",
            "quality_score": 0.5,
            "quality_rationale": "核验",
            "pointers": [],
            "index": {"headline": "", "keys": [], "evidence": []},
        }
    ]


def budget_context_data() -> list[dict[str, JsonValue]]:
    """完整的离线原料。"""
    return [{"kind": "hard", "scope": "run", "unit": "actions", "source": "fixture", "limit": 50}]


def run_example() -> RunPlanParams:
    """含历史全文、索引和反馈的 run。"""
    return RunPlanParams.model_validate(
        {
            "run_goal": {"goal": "读取招牌", "criteria": "取得招牌文字"},
            "plan": plan_data(),
            "observation": observation_data(),
            "details": details_data(),
            "run_index": run_index_data(),
            "terrain_meanings": {".": "可走", "#": "墙"},
            "human_note": "先确认字面内容",
            "budget_context": budget_context_data(),
            "knowledge": ["知识甲全文", "知识乙全文"],
            "last_judge": {"decision": "continue", "why": "继续核对", "note": "反馈全文"},
            "max_push": 2,
            "remaining_planning_rounds": 3,
            "execution_order": ["existing:0"],
        }
    )


def observation_data() -> dict[str, JsonValue]:
    """当前帧具有完整四邻。"""
    return {
        "step": 2,
        "scene": "walk",
        "place": {"map_id": 1, "x": 2, "y": 3},
        "facts": {
            "overlay": "none",
            "facing": "up",
            "neighbor_cells": {"up": ".", "down": ".", "left": "#", "right": "."},
        },
    }


def task_data() -> dict[str, JsonValue]:
    """含全文与首末图的 task。"""
    return {
        "run_id": "r",
        "episode_id": "e",
        "task_id": "t",
        "goal": "读取招牌",
        "termination": "goal_done",
        "steps_used": 2,
        "total_acts": 2,
        "summary": "任务首句。完整招牌原文。",
        "quality_score": 0.5,
        "quality_rationale": "核验",
        "facts": [],
        "pointers": [],
        "index": {"headline": "", "keys": [], "evidence": []},
        "first_frame": "FRAME_FIRST",
        "last_frame": "FRAME_LAST",
    }


def episode_example(base: dict[str, JsonValue]) -> DecomposeParams:
    """从同一批原料构造本层公开参数。"""
    return DecomposeParams.model_validate(
        {
            **base,
            "goal": base["run_goal"],
            "max_tasks": 2,
            "task_memories": [task_data()],
            "episode_index": base["details"],
            "task_table": [{"entry_id": "entry", "round": 1, "task": base["plan"][0]["task"]}],
        }
    )


def choose_example(base: dict[str, JsonValue]) -> DecideActionParams:
    """从同一批原料构造本层公开参数。"""
    return DecideActionParams.model_validate(
        {
            **base,
            "goals": [{"goal": "背景目标", "criteria": "背景判据"}, base["run_goal"]],
            "space": {"names": ["up", "a"]},
            "knowledge": "\n\n".join(base["knowledge"]),
            "task_index": [task_data()],
            "memories": [
                {
                    "episode_id": "e",
                    "step": 1,
                    "before": observation_data(),
                    "after": observation_data(),
                    "action": "a",
                    "observations": [],
                    "outcome": None,
                    "result": "动作完整结果",
                    "before_frame": "FRAME_FIRST",
                    "after_frame": "FRAME_LAST",
                }
            ],
            "last_result": "脚本完整结果",
            "max_segments": 3,
        }
    )


def examples() -> dict[str, RunPlanParams | DecomposeParams | DecideActionParams]:
    """三个层级共享相同的观测、目标和知识原料。"""
    run = run_example()
    base = run.model_dump(mode="json")
    episode = episode_example(base)
    choose = choose_example(base)
    return {"run_plan": run, "decompose": episode, "decide_action": choose}
