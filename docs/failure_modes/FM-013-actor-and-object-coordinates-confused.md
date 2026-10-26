# FM-013 执行者站位与交互对象坐标混淆

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：规划/对象归属
- 状态：有多次实例；知识候选，未单独验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

把主角相邻站位写成NPC所在格，导致走错位置、转错向或重新规划。

## 证据与定位

iter06后续规划纠正第二NPC在(5,7)，原来当成(5,6)；额外移动和拆解导致ACT6→11。

## 根因与确认边界

地图物体坐标、actor所在格、交互触发位置没有分角色解释。

## 处理方向与取舍

知识区分对象/主角/交互位置；prompt只写通用角色与证据归属方法，不植入特定样本路线。

## 验收要点

核对对象格、相邻执行格、朝向及实际交互对象，不能以主角站位代替对象身份。

## 原始记录

- [eval_results/overnight3/iter06/ROUND_REPORT.md](../../eval_results/overnight3/iter06/ROUND_REPORT.md)
- [eval_results/overnight3/iter11/ROUND_REPORT.md](../../eval_results/overnight3/iter11/ROUND_REPORT.md)
