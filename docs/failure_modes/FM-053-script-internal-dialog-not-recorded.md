# FM-053 脚本内的对话与自动过场不进账

- 整理日期：2026-10-27（Europe/Berlin）
- 分类：观测与记忆缺失
- 状态：665–666 补了 `dialog` 字段，667–668 由逐键观察取代；对象记忆将在 CP4 删除
- 适用边界：证据来自代码与 trace 的字段清单，没有逐条回放；"自动过场没有事件"是由判定规则推出的，需要在领包裹这一段实测核对。

## 现象与触发

一口气按完的脚本（`advance_dialog`、`talk_to_adjacent_npc`、`walk_to` 进店等）中间出现的文字，只剩前后两帧；进店自动触发的领包裹过场不是按键撞到物体，没有任何事件。收件人（PROF. OAK、PALLET TOWN）这类只出现一次的证据因此可能从账里消失。

## 证据与定位

- 真实 trace 里脚本的 `act_call` 只有 `script`、`args`、`ok`、`code`、`events` 五个字段；`pokemon_agent/world/scripts/dialog_cache.py` 每键收集的增量文字在脚本结束后被丢弃。
- `world/object_events.py` 的判定要求"本次按键的候选格里有交互物"，自动过场没有候选物体。
- 评分器 `scorer/rules/shop.py`、`overshoot_scorer.py` 依赖这套事件。

## 根因与确认边界

脚本把内部过程压成一步，观察只在首尾；事件只在撞到物体时产生。稳定等待是否会在文字中途停顿时提前读到半截，尚未实测（探针脚本 `experiment/probe_settle.py` 已写、未运行）。

## 处理方向与取舍

脚本内每键一份紧凑观察进终态报告与账，`ActMemory` 携带观察序列，摘要的事实块由相邻观察的差异机械摘出并保留；观察带 `settled` 标记，超时的文字不当证据。

## 验收要点

一次进店领包裹的脚本调用，观察序列里能依次读到进门、对话各行、背包多出包裹；摘要事实块与索引关键词含收件人。

## 原始记录

- docs/step_observation/intent.md、spec.md
- docs/script_dialog/intent.md
