"""真实链路核对脚本（独立进程，不用 pytest）。

四个维度各一个可单独执行的脚本：`check_harness`（跑得完）/ `check_trace`
（记账落盘）/ `check_checkpoint`（存档配对）/ `check_memory`（记忆落盘自洽）。
拆成独立进程是为了隔离"接真实依赖才现形的硬崩溃"——pytest 单进程跑会把
崩溃点糊在一起，一个文件一个进程，谁崩一眼定位。

用法（从项目根目录，先导出两个 key）：

    export ARK_API_KEY=... DASHSCOPE_API_KEY=...
    python -m pokemon_agent.experiment.real_check.check_harness
    python -m pokemon_agent.experiment.real_check.check_trace
    python -m pokemon_agent.experiment.real_check.check_checkpoint
    python -m pokemon_agent.experiment.real_check.check_memory
"""
