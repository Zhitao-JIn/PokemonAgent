# FM-046 预算收尾跳过已存在task正文

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：记忆/收尾
- 状态：历史已确认；当前预算路径未本次复核
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

已有task摘要和交互证据，上层最终材料却显示“本局无正文”。

## 证据与定位

overnight010 epoch1 task摘要call 01a169ec-7c02-729d-ae1b-2b2855737744与dialog事件01a169ec-458f-7fd5-ae30-f495bbb3de24存在，预算分支直接leave_chapter。

## 根因与确认边界

BUDGET_TERMINATIONS收尾绕过已有记忆蒸馏，并把跳过误述为没有记忆。

## 处理方向与取舍

预算不足可停止新增模型调用，但应保留已有事实/摘要与真实跳过原因；不能因无新蒸馏就抹掉下层证据。

## 验收要点

预算/中断路径仍能追溯已有task内容，来源章与正文不互相冒充；不靠摘要补不存在动作。

## 原始记录

- [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md)
