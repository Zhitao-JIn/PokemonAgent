# FM-011 分页结果文字被单帧正则漏判

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：机械评分
- 状态：用户授权修复并仅离线校正iter01
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

真实成功文字已出现，机械评分I并产生派生R3，独立评分C。

## 证据与定位

iter01先有“All right! PIDGEY was”，后有“PIDGEY was caught!”；旧正则要求单帧all right!.*was caught，不接受独立完整结果句。

## 根因与确认边界

展示分页边界不等于语义结果边界，规则遗漏合法完整句。iter00只见半句，不能追溯套用iter01证据。

## 处理方向与取舍

保持“必须有实际完整结果”约束，接受合法完整was caught句；冻结原trace与原分，保存校正provenance。

## 验收要点

完整结果句可过；只有投球动作、半句、开局已有结果均不可过；不扩大修正到无证据轮次。

## 原始记录

- [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md)
- [docs/eval/spec.md](../eval/spec.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
