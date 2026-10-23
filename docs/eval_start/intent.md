# 评测轻起点 + 评测自起临时服务 —— intent（2026-10-23）

## 要解决的问题

1. **存档起点太重、太脆。** `agent_short_goal_run` 的样本从「run 级存档」起跑：离线 `pack` 产出 manifest + world.state + 记忆 zip，评测时 `restore_run` 校验 `state_schema_hash`、回档记忆、回档世界。`RunState` / `EpisodeRunState` / `TaskState` 任一字段变动，所有存档拒载（2026-10-23 通宵调优在基线阶段即被卡死）。而存档里真正有价值的只有 `world.state`；`run_state` 只是「目标 + 判据」，样本里本来就有；记忆快照是空 zip，却要走会清空 knowledge 的 restore。
2. **评测服务是手工起的、共用的。** 评测前要自己起 world / memory 服务并设置 `MCP_*_SERVER_URL`；URL 多写一个 `/mcp` 就全军覆没（2026-10-23 的 20/20 打包失败）；服务用固定目录，评测会清空它；knowledge 在评测里是否真正可用无人保证。

## 用户的决定

- 评测起点用**最轻版本**：样本自带的原始 `.state` + 样本的目标现建 Task，直接起跑；不要存档，不走 `restore_run`。之前所有「存档恢复可选 knowledge」的讨论作废（生产的 `restore` / `snapshot` 语义不动）。
- 评测所用的**所有服务都用临时目录**，knowledge 临时复制一份。
- 不要统一入口、不要包装命令：评测一律用原生命令（`inspect eval …`、`python -m evals.<任务>`）；服务由 solver / 脚本内部的一个上下文管理器起，**solver 运行结束即关闭**。

## 范围

- 做：样本起点改为原始 `.state`；删存档相关代码；新增 `eval_services` 上下文管理器；四个评测入口接入。
- 不做：不改 harness 的 checkpoint 保存/恢复（仍可用于调试与续跑）；不改 `snapshot` / `restore` 语义；不改状态模型；不改冻结数据集内容（`samples.jsonl` 等原样保留）；不做 prompt / knowledge 调优（另案，本项完成后重发交接）。
