"""evals：Pokemon_Agent 的测评体系（`docs/eval/`）。被测系统的外部使用方——只经 `build_real` /
`restore_run` / world 的公开接口起跑、只读 trace 与存档；
`pokemon_agent/` 内任何代码都不 import 本包。

**一项测评一个子包**，不同类的不混放（各自的数据集、判定、报表、产物目录都在自己名下）：

- `e2e/`：端到端——一条样本从 run 入口跑完，出结果层 / 红线 / 路径层 / 过程层 / 效率层报告；
- `macros/`：宏——从存档调 world 的宏，核对结局、原因码、状态变化与收尾画面（不调模型）；
- `takeover_views/`：接管视图——各接管场合初态帧的视图逐字段核对（不调模型）；
- `screen_reading/`：task 层无视觉读屏——把 task 层看到的字段 + 整屏原样喂给模型，看它读不读得懂。

命令行：`python -m evals <测评> <命令>`（`cli.py` 只做分派）。
产物落 `eval_results/<测评>/`（不进 git）。
"""
