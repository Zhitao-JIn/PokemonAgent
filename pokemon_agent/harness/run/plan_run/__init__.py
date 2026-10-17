"""`plan_run` 格：**要一版规划 → 插话 → 落表**。停机不归本格。

单文件格：单元就是 `plan_run.py`。全部局详情、过往 run 背景与知识
从 `state.plan_ctx` 读（`perceive` 格写的）。
"""

from .plan_run import plan_run

__all__ = ["plan_run"]
