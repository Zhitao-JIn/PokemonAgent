# FM-017 子任务要求读取未提供的后台记录

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：拆解/验收
- 状态：decompose v7候选；iter17有改善线索
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

现场效果已发生，子任务判定却要求额外结构化后台记录，反复续做。

## 证据与定位

iter16/B商店25ACT，机械首次完成后续做13ACT；task judge seq295承认对话已发生但称“未见该结构化记录”。

## 根因与确认边界

上层账本字段直接抄入下层验收，而下层输入只有观测及动作历史。

## 处理方向与取舍

父目标保留，上层记录要求映射为下层可观察效果；不为让后台记录“出现”再按键，不假称未收到的记录存在。

## 验收要点

效果明确时及时停；证据不足仍补可取得的观察，不能通过删除父目标约束过关。

## 原始记录

- [eval_results/overnight3/iter16/ROUND_REPORT.md](../../eval_results/overnight3/iter16/ROUND_REPORT.md)
- [eval_results/overnight3/iter16/ANALYSIS.json](../../eval_results/overnight3/iter16/ANALYSIS.json)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
