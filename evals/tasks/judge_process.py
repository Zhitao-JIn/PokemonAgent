"""judge 过程集的 task 留位（spec2 §六取舍 B）。

v1 的 judge 一致性（TP/FP/FN/TN）与机械判定消费同一个 run 的产物，挂 e2e task
的附加 scorer（`evals/e2e/process/judge_agreement.py`），不拆独立 task；将来过程集
扩充（拆解质量 / 卡住换策略，需要独立样本与打分流程）时在此启用。
"""

from __future__ import annotations
