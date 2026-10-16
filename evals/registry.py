"""五个公开评测任务的类型与入口；不导入任务实现。"""

from typing import Literal

from pydantic import BaseModel


class TaskEntry(BaseModel):
    """DeepEval 使用模块入口，Inspect 使用 task 文件入口。"""

    kind: Literal["deepeval", "inspect"]
    entry: str


TASKS: dict[str, TaskEntry] = {
    "decode": TaskEntry(kind="deepeval", entry="evals.decode"),
    "memory_store_recall": TaskEntry(kind="deepeval", entry="evals.memory_store_recall"),
    "world_script_execute": TaskEntry(kind="deepeval", entry="evals.world_script_execute"),
    "brain_goal_judge": TaskEntry(kind="inspect", entry="evals/brain_goal_judge/task.py"),
    "agent_short_goal_run": TaskEntry(kind="inspect", entry="evals/agent_short_goal_run/task.py"),
}
