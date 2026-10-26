# FM-020 execution_order引用不存在或错误状态的条目

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化规划
- 状态：已有显式校验/纠正；错误模式仍需保留
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

混用task_id、表序号、排序后位置或new/existing索引，漏列/重复待办。

## 证据与定位

overnight首轮有两次decompose execution_order解析失败；当前规划纠错测试覆盖[failed,pending,pending]应引用existing:1/:2等。

## 根因与确认边界

模型输出的引用空间与状态表原始索引不一致，状态更新后的pending集合又发生变化。

## 处理方向与取舍

先应用updates再核对全部pending，纠错明确合法引用；不能悄悄替模型补执行顺序。

## 验收要点

新增、放弃、重开、保留混合时引用完整且唯一；失败账和纠正请求都可追踪。

## 原始记录

- [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
