"""真实链路核对脚本（独立进程，不用 pytest）。

四个维度各一个可单独执行的脚本：`check_harness`（跑得完）/ `check_trace`
（记账落盘）/ `check_checkpoint`（存档配对）/ `check_memory`（记忆落盘自洽）。
拆成独立进程是为了隔离"接真实依赖才现形的硬崩溃"——pytest 单进程跑会把
崩溃点糊在一起，一个文件一个进程，谁崩一眼定位。

用法（从项目根目录；密钥由 `common.load_env_file()` 自动从仓库根 `.env` 注入，
已在外部环境设过同名变量则以其为准）：

    python -m experiment.real_check.check_harness
    python -m experiment.real_check.check_trace
    python -m experiment.real_check.check_checkpoint
    python -m experiment.real_check.check_memory
    python -m experiment.real_check.check_memory_roundtrip
    python -m experiment.real_check.check_restore [--step N]

`check_restore` 的 `--step` 选恢复点：不给则取最后一个存档步。末步恢复**也会**归档该局的
跨局摘要（局收尾在最后一个 checkpoint 之后，任何恢复点都会把那次收尾圈进废弃窗口）；
但末步不写 step 记忆，要额外压到 step 记忆的归档路径得用 `--step 1` 从中间步恢复。
`resume_only` 是调试口（只跑恢复半程、无断言）。
"""
