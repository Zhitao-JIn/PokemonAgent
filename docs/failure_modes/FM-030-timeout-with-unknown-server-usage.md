# FM-030 模型超时留下未知服务端费用和重试链

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：接口/计费
- 状态：历史与近期均有；不能靠prompt保证消除
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

本地超时但服务端可能继续生成；本地usage无法证明费用为0。

## 证据与定位

iter01一次decompose ToolTimeout；iter14/full verify两次超时加一条call_exhausted，共3条事件同一调用链。

## 根因与确认边界

客户端等待与服务端生成/计费生命周期不同；事件数也不等于独立事故数。

## 处理方向与取舍

保留超时/耗尽账、未知费用说明及在途余量，按错误性质有限重试；不猜零账或一律按全未命中补账。

## 验收要点

已落盘费用与未知部分分列，调用链可关联，不重复或遗漏计数。

## 原始记录

- [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md)
- [eval_results/overnight3/iter14/ROUND_REPORT.md](../../eval_results/overnight3/iter14/ROUND_REPORT.md)
- [eval_results/overnight3/iter14/ANALYSIS.json](../../eval_results/overnight3/iter14/ANALYSIS.json)
