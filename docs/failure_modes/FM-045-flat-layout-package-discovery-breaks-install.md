# FM-045 多顶层目录导致editable安装包发现失败

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：工程/打包
- 状态：2026-09历史包发现修复；运行环境另有版本限制
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

pip install -e .[dev]报Multiple top-level packages discovered in a flat-layout。

## 证据与定位

日志列log/web/assets/config/evaluation/trace_data/pokemon_agent；补packages.find include后发现阶段通过，但当时本机Python3.10仍低于项目3.11要求。

## 根因与确认边界

仓库运行产物/文档目录被自动包发现误收；包发现与Python版本是两类问题。

## 处理方向与取舍

显式限制包范围；环境版本独立核对，不把安装初步通过说成全量运行验证。

## 验收要点

干净环境editable构建可定位正确包；所需Python版本与实际测试证据明确。

## 原始记录

- [docs/experiences/2026-09-01-trace-task-id-and-memory-carried.md](../experiences/2026-09-01-trace-task-id-and-memory-carried.md)
