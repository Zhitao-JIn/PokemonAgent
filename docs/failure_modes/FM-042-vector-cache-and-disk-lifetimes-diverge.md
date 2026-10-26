# FM-042 向量缓存与磁盘记忆生命周期不一致

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：记忆/缓存
- 状态：2026-08历史已修；现有实现未本次重测
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

跨run检索历史摘要时，缓存没有相应ID，发生KeyError。

## 证据与定位

历史episode_id属于上一个run；FileEpisodeMemoryStore读全部磁盘摘要，进程内_episode_memory_vectors只存本run新摘要。

## 根因与确认边界

持久事实集合与进程派生索引集合不一致。

## 处理方向与取舍

历史修法为按需惰性补embedding并缓存；原始摘要才是真相，不靠只读本run逃避合法跨run检索。

## 验收要点

缓存空、磁盘有历史记录也能查询，且同条向量不反复重算。

## 原始记录

- [docs/experiences/2026-08-31-keyerror-cross-run-leak.md](../experiences/2026-08-31-keyerror-cross-run-leak.md)
