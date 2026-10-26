# FM-032 变量或条件分支切断静态缓存前缀

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：缓存布局
- 状态：多版布局已调整；收益依场景验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

固定规则被goal/scene/观测夹断；字符上静态很多，实际可复用连续前缀很短。

## 证据与定位

旧轮整体40.9%，plan/run摘要0%、task摘要7.8%；decide_action条件map_guide为早期断点，v4/v5前缀2635→3749字符。

## 根因与确认边界

前缀缓存依连续相同输入，不是任意固定文字都能被命中；条件分支还可能拆成不同前缀族。

## 处理方向与取舍

静态说明前置、动态材料后置；只改布局时冻结词语/素材，实际统计cached_tokens，不把字符等同token。

## 验收要点

真实调用未命中输入和费用有证据变化，正确率不降；短前缀或首次冷请求不承诺命中。

## 原始记录

- [.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md](../../.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md)
- [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md)
- [eval_results/overnight3/iter06/ROUND_REPORT.md](../../eval_results/overnight3/iter06/ROUND_REPORT.md)
