"""端到端测评：样本从 run 入口跑完，按盘上 trace 出报告（`docs/spec/evals/SPEC.md`）。

子包：`schemas`（契约）、`dataset`（数据集）、`runner`（批跑）、`checks`（机械判据）、`rubric`、
`process`（从 e2e 账本上算的过程指标：judge 一致性、感知一致率）、`report`（判定与报表）、
`cases`（bad case）。命令行 `python -m evals e2e …` 见 `cli.py`。
"""
