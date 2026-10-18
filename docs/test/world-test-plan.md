# plan —— world 模块单元测试：检查点、编号与验收

> 依据：`docs/test/world-test-spec.md`；intent 见项目文档 `claude/world-test-intent.md`（已确认）。
> 分支：`tests/world-unit`，基线 `29f282a`（= main）。

## 一、角色

- 设计侧：写文档、派发、验收、提交。
- 执行方：只改允许文件、跑三项检查、写 CHANGELOG（用给定编号）、停下汇报。不提交。

## 二、检查点

| 序 | 编号 | 内容 | 依赖 |
|---|---|---|---|
| CP1 | 521 | 纯逻辑小模块（29 条，见 spec 第二节） | 无 |
| CP2 | 533 | 场景与菜单 | CP1 |
| CP3 | 537 | 读数、地形精灵、地图表、帧编码、ram 解码（spec 第七节，21 项） | CP2 |
| CP4 | 派发时分配 | `pyboy_world` 前置条件；`object_events`、`task_perception`、`tables/` 三张表（自 CP3 移入） | CP3 |
| CP5 | 派发时分配 | 迁入 mcp 世界逻辑用例，删除 mcp 侧原用例 | CP4 |

编号：CP1 为 521（已登记台账）；CP2 为 533（已登记台账）；CP3 为 537（spec 已写，已登记台账）；CP4–CP5 在各自派发时由设计侧分配并登记台账。CP5 的 CHANGELOG 与 mcp 线同一条。

## 三、允许改动的文件（CP1）

- 新增：`tests/world/test_world_action_space.py`、`tests/world/test_screen_glyphs.py`、`tests/world/test_items.py`、`tests/world/test_moves.py`
- 修改：`CHANGELOG.md`（仅顶部一条）
- 不得改动：`pokemon_agent/` 下任何文件（破坏验证还原后除外）、`tests/world/scripts/`、`tests/world/test_screen_text.py`、`tests/world/test_action_space_scripts.py`

## 四、CP1 验收

1. `git diff --stat` 只涉及第三节的允许文件；`--ignore-cr-at-eol` 核对行尾未被整体改写。
2. junit 计数：tests = 基线 + 29，failures = 0，errors = 0，skipped = 0。
3. `tests/world/` 耗时 ≤ 5 秒。
4. spec 第五节的四处破坏验证，每处对应用例失败，还原后 `git diff pokemon_agent/` 为空。
5. CHANGELOG 数字来自实测（用例数、junit 计数），不写估算值。
6. `ruff check .` 与 `ruff format --check .` 全绿。
