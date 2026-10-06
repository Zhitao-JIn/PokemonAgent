"""task 侧薄适配：真库 `@task` / `Task` / `Epochs` 的 re-export（R0 实测口径，0.3.271）。

每类测评一个 task 定义（`evals/tasks/`）；本项目不使用的真库面（sandbox、agent、
tool 协议）不在此暴露——要用先回 spec2 议。
"""

from __future__ import annotations

from inspect_ai import Epochs, Task, task

__all__ = ["Epochs", "Task", "task"]
