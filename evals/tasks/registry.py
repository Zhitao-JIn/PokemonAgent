"""迁移中的 Inspect 任务目录；DeepEval 任务已有独立模块入口。"""

TASKS: dict[str, str] = {
    "brain_goal_judge": "evals/tasks/brain_goal_judge/task.py",
    "agent_short_goal_run": "evals/tasks/agent_short_goal_run/task.py",
}
