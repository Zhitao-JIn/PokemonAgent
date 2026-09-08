"""experiment 包：实验 manifest、任务定义、跑批入口。

各 `run_*.py` 可作为脚本独立执行（`python -m pokemon_agent.experiment.run_experiment`）；
需要被 import 复用的部分（任务定义、manifest、会话装配、跑批统计）从这里出口。

本文件是统一出口：消费方只写 `from pokemon_agent.experiment import X`，
不深到模块文件；包内模块之间走相对 import。
"""

__all__ = [
    "RunManifest",
    "TaskChain",
    "batch_run_ids",
    "build_session",
    "knowledge_recall_tasks",
    "read_outcomes",
    "run_chain",
    "run_one",
    "state_for_task",
    "update_task_stats",
]
from .manifest import RunManifest
from .run_all_tasks import batch_run_ids, read_outcomes
from .run_episode import build_session, run_one
from .run_experiment import run_chain, state_for_task, update_task_stats
from .tasks import TaskChain, knowledge_recall_tasks
