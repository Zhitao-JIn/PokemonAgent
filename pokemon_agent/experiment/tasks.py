"""可重复的短程/长程实验任务定义。"""

from __future__ import annotations

from pokemon_agent.schemas.task import Task


def knowledge_recall_tasks(max_steps: int = 12) -> list[Task]:
    """围绕野生遭遇知识设计的短程任务，目标文本必须触发 knowledge 检索。"""
    goals = (
        "在草丛中连续行走，直到遇到一只野生宝可梦",
        "想触发野生宝可梦遭遇，不要只按一次方向键",
        "进入草丛深处并确认是否进入战斗场景",
    )
    return [
        Task(task_id=f"knowledge_wild_encounter_{index}", goal=goal,
             success_criteria="画面出现野生遭遇或战斗场景的直接证据", max_steps=max_steps)
        for index, goal in enumerate(goals, start=1)
    ]


def episodic_recall_tasks(max_steps: int = 80) -> list[Task]:
    """需要跨局摘要经验的长程任务；先失败积累轨迹，再重复同一目标测召回。"""
    goal = "从当前起点穿过野外路线并进入下一个城镇"
    return [
        Task(task_id=f"episodic_route_trial_{index}", goal=goal,
             success_criteria="画面出现下一个城镇的直接证据", max_steps=max_steps)
        for index in range(1, 4)
    ]
