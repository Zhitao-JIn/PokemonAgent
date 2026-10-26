# FM-002 拆解prompt缺少建议预算与硬预算的完整上下文

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：预算/输入
- 状态：641已补传预算，离线回归通过，待真实模型验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

模型不知道父级建议数、配置硬上限及各自剩余额度，收到的建议上限与执行时硬闸不一致。

## 证据与定位

iter19三次decompose prompt都显示“本次新增建议上限：5”“剩余拆解轮数：12”，不含父级budget.limit=1。_request使用全局episode_max_tasks减state.step；实际执行却按goal.max_steps=1停。

## 根因与确认边界

GoalDefinition只有goal/criteria；max_tasks是新增建议量，不是完整预算账，拆解轮数又是另一种单位。不能说模型明知只有1个task仍违规。

## 处理方向与取舍

按最新语义同时传父级建议、配置硬上限、已用/剩余、单位和来源，明确“建议”和“硬限制”。此前建议把goal.max_steps继续作为硬上限的修法已被用户澄清取代，不能照旧实施。

## 验收要点

真实渲染prompt能逐项看到两类预算；父级建议不冒充硬闸；新增建议量不超过配置剩余额度，已有待办与新增待办有清晰口径。

## 原始记录

- [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md)
- [eval_results/overnight3/iter19/ANALYSIS.json](../../eval_results/overnight3/iter19/ANALYSIS.json)
- [pokemon_agent/harness/episode/plan_episode/plan_episode.py](../../pokemon_agent/harness/episode/plan_episode/plan_episode.py)

## 641修复追踪

[预算语义与验证](../budget/ADVISORY_AND_HARD_LIMITS.md)；[真实图回归](../../tests/budget/test_advisory_budget.py)。旧iter19失败证据保留，不以离线通过冒充付费实测成功。
