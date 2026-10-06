"""端到端测评的实现层（R2a 后）：runner（批跑）、report（判定与报表）、cases（bad case）、
rubric、process（judge 一致性、感知一致率）。命令行 `python -m evals e2e …` 见 `cli.py`。

判据与协议已迁出：判据 → `evals/scorers/`、判定货币 → `evals/core/`、数据集 → `evals/data/`、
样本契约 → `evals/schema/`。本包在 R2b/R3/R5 逐步收编退役（runner 循环交 core/evalset、
markdown 渲染退役、判定主输入换 RunResult）。
"""
