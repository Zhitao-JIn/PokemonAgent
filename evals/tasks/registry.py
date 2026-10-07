"""唯一的公开测评目录：六个 inspect task。"""

TASKS: dict[str, str] = {
    "decode": "evals/tasks/decode/task.py",
    "vision_perceive": "evals/tasks/vision_perceive/task.py",
    "world_actions": "evals/tasks/world_actions/task.py",
    "memory": "evals/tasks/memory/task.py",
    "judge": "evals/tasks/judge/task.py",
    "e2e": "evals/tasks/e2e.py",
}
