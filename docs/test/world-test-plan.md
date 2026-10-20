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
| CP4 | 545 | 物体事件、单帧装配、静态表、地形精灵与入口前置检查（spec 第八节，58 项） | CP3 |
| CP5 | 561 | mcp 迁移清单重新分类：去掉 9 条“待迁”标注，两份 intent 同步（spec 第九节；不搬文件、不删用例） | CP4 |

编号：CP1 为 521（已登记台账）；CP2 为 533（已登记台账）；CP3 为 537（已验收提交934566d）；CP4 为545（已登记，设计文档待提交）；CP5 在派发时由设计侧分配并登记台账。CP5 的 CHANGELOG 与 mcp 线同一条。

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

## 五、CP4（545）执行范围与验收

- 基线实现HEAD：`934566d7efe3729021d900d7012f4e63fadb30c2`；本轮设计文档先由用户提交，
  执行交接的基线必须换成该设计提交的实际完整HEAD，不允许猜哈希。
- spec第八节已钉34函数/58项；CP3已提交，1517为默认全量基线，world183。
- 允许新增且仅新增：
  - `tests/world/test_world_object_events.py`
  - `tests/world/test_world_terrain_map.py`
  - `tests/world/test_world_task_perception.py`
  - `tests/world/test_world_tables.py`
  - `tests/world/test_world_pyboy_world_prechecks.py`
- 允许修改：`CHANGELOG.md`顶部追加一条，编号545，四段固定格式；
  标题为`2026-10-19（545）—— world 物体事件、单帧装配、静态表与入口前置检查（CP4）`。
  实现提交加Conventional Commits前缀后逐字复用该标题。
- spec8.8列明的五个生产文件只允许临时破坏并还原，不能成为最终diff；
  JSON不改；既有测试、conftest、其他工作树与brain_scope不改。
- 写文件前记录HEAD/父提交/分支、导入路径、起点status与默认N0全量JUnit。
  已知九个`.pytest_tmp_cp3_audit*`是设计侧遗留，不删除、不覆盖、不提交。
- 验收：只允许上述五文件+CHANGELOG；新文件必须单独列入清单，
  不以git diff --stat未显示未跟踪文件为由遗漏。忽略CR行尾后stat应一致。
- 实测预期：新增58项；world241项且≤5秒；默认全量1575 passed，
  failures/errors/skipped均0；原有3项slow仍deselected；Ruff两项通过。
  如N0不是1517、实际新增计数不是58，先报告差异，不自行删改用例凑数。
- 六处破坏验证必须有真实的目标断言失败证据；逐处还原、目标复测通过；
  最终生产diff为空。构造检查不得调用真实PyBoy。
- 报告同时给出完整HEAD/父提交、stat/status、五个新文件清单、
  每文件函数/项数、N0/N1 JUnit、world耗时、Ruff、六处失败与还原证据、规范检索结果。
  执行者不执行任何git写操作，完成后停下。
- 补证报告已验收；stdout计数的118/119来自末尾空行口径，不影响内容一致。
  未知facing与门双事件不冻结；save_state后置检查、stop、all_actions不扩入本轮。
