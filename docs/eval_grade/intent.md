# 独立结果评分与 judge 同视野 —— intent（2026-10-23）

## 问题（有证据）

2026-10-23 的 e2e 调优基线（两个样本各 3 次）：机械评分通过 5/6，独立结果评分（`evals/agent_short_goal_run/scorer/result_grade.py`）通过 1/6。独立评分的回复明确说「最终观测未包含 scene 字段」「未提供任务历史中两个不同起点 NPC 位置各自的交互记录」。原因：`final_evidence` 只把最终帧的 `place` 与 `ram` 交给评分模型，而样本判据大量要看 scene / overlay / options / 历史（20 个样本里约一半）。评分器没拿到判据所需的材料，所以「调 prompt 修好样本」得不到有效信号。

## 用户的决定

独立结果评分应当与内部 judge **同一视野**：评分模型看到 judge 在最后一次判定时看到的同样材料。

## 做什么

- 独立评分的证据改为：被测系统最后一次 `judge_call`（trace 里已记录其完整 `prompt`）的材料，加上样本的目标与判据；评分模型只回答「结果是否达成」，不评路径。
- 顺带：`agent_short_goal_run` 的评测 memory 服务开 admin（之前手工起服务时就是带 `--enable-admin`），消除 harness 开局保存 checkpoint 时每个样本 5 条 `checkpoint_error`（MemoryAdminDisabled）的噪声。

## 不做

不改机械评分与判据；不改数据集与样本；不改 judge 的 prompt（judge 措辞与跨帧判读的问题另案，等评分恢复可用后再做 prompt 实验）；不改 `eval_services`。
