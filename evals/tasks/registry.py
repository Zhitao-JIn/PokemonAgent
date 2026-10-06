"""唯一的公开测评目录：七个 inspect task。"""

TASKS: dict[str, str] = {
    "decode": "evals/tasks/decode/task.py",
    "vision_perceive": "evals/tasks/vision_perceive/task.py",
    "screen_interpret": "evals/tasks/screen_interpret/task.py",
    "world_actions": "evals/tasks/world_actions/task.py",
    "memory": "evals/tasks/memory/task.py",
    "judge": "evals/tasks/judge/task.py",
    "e2e": "evals/tasks/e2e.py",
}
