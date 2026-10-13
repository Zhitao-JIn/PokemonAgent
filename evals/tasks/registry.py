"""唯一的公开测评目录：五个 inspect task。"""

TASKS: dict[str, str] = {
    "episode_vision_read": "evals/tasks/episode_vision_read/task.py",
    "world_script_execute": "evals/tasks/world_script_execute/task.py",
    "memory_store_recall": "evals/tasks/memory_store_recall/task.py",
    "brain_goal_judge": "evals/tasks/brain_goal_judge/task.py",
    "agent_short_goal_run": "evals/tasks/agent_short_goal_run/task.py",
}
