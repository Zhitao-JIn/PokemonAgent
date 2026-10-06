"""宏测评：从存档出发调 world 的宏，核对结果码、状态变化与收尾画面。

每个宏至少三例：成功、被拒、从中途步骤开跑（存档本身停在中途，或开跑前先按几个键）。
不调模型、不花钱；只经 world 的公开接口（`PyBoyWorld.reset` / `step` / `perceive_task` /
`run_macro`）。

命令行：`python -m evals macros run [--cases a,b]`，见 `cli.py`。产物落 `eval_results/macros/`。
"""
