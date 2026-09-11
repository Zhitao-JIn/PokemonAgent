"""experiment 包（仓库根级）：实验任务定义、状态存档、真实链路核对。

只保留三样东西（0910 拍板）：`tasks.py`（任务定义 + goal/criteria 写法规范）、
`experiment_states/`（知识库探索用的钉死存档）、`real_check/`（六个维度的
真实链路核对脚本）。跑批入口 / manifest / 会话装配已随 agent_permission
移除一并退役。

real_check 各脚本独立执行：

    python -m experiment.real_check.check_harness
    python -m experiment.real_check.check_trace
    python -m experiment.real_check.check_memory
    python -m experiment.real_check.check_memory_roundtrip
    python -m experiment.real_check.check_restore

本文件是统一出口：消费方只写 `from experiment import X`，不深到模块文件；
包内模块之间走相对 import。
"""

__all__ = [
    "TaskChain",
    "knowledge_recall_tasks",
]

from .tasks import TaskChain, knowledge_recall_tasks
