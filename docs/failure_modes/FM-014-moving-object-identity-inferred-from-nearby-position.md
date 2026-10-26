# FM-014 移动对象当前位置被当成起点对象身份凭据

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：判定假阳
- 状态：judge v6/NPC知识候选；尚无身份机制保证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

见到邻近NPC位置和摘要描述就认定完成原起点对象，机械只匹配一位。

## 证据与定位

iter12商店机械2/3、result3/3、R3：起点第二NPC(5,7)，交互记录为(5,6)，run用当前位置/摘要推定对应。

## 根因与确认边界

参考时刻、对象身份和位置变化被混为一谈；坐标接近或叙述并非可靠身份映射。

## 处理方向与取舍

判定区分起点与当前集合，逐对象核对直接证据；有稳定目标优先选，缺映射不猜成功。

## 验收要点

移动对象与相邻不同对象的正负对照都核验；不通过放宽机械锚点掩盖缺证。

## 原始记录

- [eval_results/overnight3/iter12/ROUND_REPORT.md](../../eval_results/overnight3/iter12/ROUND_REPORT.md)
- [eval_results/overnight3/iter12/ANALYSIS.json](../../eval_results/overnight3/iter12/ANALYSIS.json)
- [eval_results/overnight3/iter13/ROUND_REPORT.md](../../eval_results/overnight3/iter13/ROUND_REPORT.md)
