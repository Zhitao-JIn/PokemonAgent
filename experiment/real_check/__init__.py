"""真实链路核对脚本（独立进程，不用 pytest）。

各维度各一个可单独执行的脚本：`check_harness`（跑得完）/ `check_trace`
（记账落盘）/ `check_memory`（记忆落盘自洽）/ `check_memory_roundtrip`
（记忆读写回环）。
拆成独立进程是为了隔离"接真实依赖才现形的硬崩溃"——pytest 单进程跑会把
崩溃点糊在一起，一个文件一个进程，谁崩一眼定位。

用法（从项目根目录；密钥由 `common.load_env_file()` 自动从仓库根 `.env` 注入，
已在外部环境设过同名变量则以其为准）：

    python -m experiment.real_check.check_harness
    python -m experiment.real_check.check_trace
    python -m experiment.real_check.check_memory
    python -m experiment.real_check.check_memory_roundtrip

**原 checkpoint 维度已删**（`check_checkpoint` / `check_restore` / `resume_only`）：
存档与恢复链整体删除，核对脚本随之删掉（见 `CHANGELOG.md` 本次条目）。
"""
