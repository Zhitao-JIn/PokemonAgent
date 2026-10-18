# spec —— world 模块单元测试：契约与用例

> 依据：world 线 intent（项目文档 `claude/world-test-intent.md`，已确认）。
> 状态：CP1 写到用例级；CP2–CP5 仅列范围，进入该检查点时再补用例。
> 分支：`tests/world-unit`，基线 `29f282a`（= main）。

## 一、决定

| 编号 | 决定 | 理由 |
|---|---|---|
| D1 | 只经公开函数与手写假件测试，不用 `MagicMock`，不测 `_` 开头的私有成员 | intent 第四节第 2、4 条 |
| D2 | 纯函数用真实输入（字节、字表、真实域模型）构造，不起模拟器、不读 ROM | intent 第四节第 1 条 |
| D3 | 文档化的前置条件用 `pytest.raises(AssertionError)` | intent 第四节第 3 条 |
| D4 | 与现有测试重复的用例不再写：`test_world_action_space.py` 不重复 `test_action_space_scripts.py` 已有的两条 | 避免同一断言两处维护 |
| D5 | 文件名全仓唯一（`test_world_action_space.py` 因 `tests/mcpclient/action_space/test_action_space.py` 已存在而改名） | intent 第四节第 6 条 |

## 二、CP1：纯逻辑小模块（29 条）

### 2.1 `pokemon_agent/world/action_space.py`（7 条）→ `tests/world/test_world_action_space.py`

后置条件（来自源码 docstring）：`mask` 覆盖整个命名空间；不可用的键显式为 `False`；动作空间永不为空；脚本接管场合只开放基础按键。

1. `test_mask_covers_the_whole_namespace_with_keys_and_scripts`：`mask` 的键 = `all_actions` ∪ 本场合脚本名。
2. `test_unavailable_key_is_listed_as_false_not_omitted`：此刻不可用的键在 `mask` 里存在且为 `False`。
3. `test_basic_keys_stay_open_when_no_overlay_and_no_takeover`：无 overlay、无接管时，`BASIC_KEYS` 全部开放。
4. `test_overlay_actions_replace_plain_keys_for_that_overlay`：有 overlay 时，只开放 `OVERLAY_ACTIONS[overlay]` 中且在 `all_actions` 里的键，加上基础键。
5. `test_takeover_scene_closes_plain_keys_except_basic_keys`：`covered_by_script` 为真的场合，非基础键全部关闭。
6. `test_empty_action_space_is_refused_by_assertion`：无 overlay、`all_actions=[]`、场合无脚本，触发 `AssertionError`。
7. `test_takeover_flag_disagreeing_with_registry_is_refused`：`obs.covered_by_script` 与场合注册表不一致时触发 `AssertionError`。

注：`test_action_space_scripts.py` 已有的两条不重复写。

### 2.2 `pokemon_agent/world/screen_glyphs.py`（10 条）→ `tests/world/test_screen_glyphs.py`

1. `test_has_text_neighbor_true_for_text_on_the_left`
2. `test_has_text_neighbor_true_for_text_on_the_right`
3. `test_a_black_block_neighbor_is_not_text`：邻格是 `0xFF` 不算文字。
4. `test_edge_column_counts_only_the_existing_neighbor`：列 0 只看右邻。
5. `test_erased_tiles_counts_black_blocks_without_text_neighbors`
6. `test_erased_tiles_ignores_black_blocks_next_to_text`
7. `test_title_logo_needs_sixteen_consecutive_tiles_on_row_one`：`tiles[1][2:18] == 0x80..0x8F` 为真；偏移一格即为假。
8. `test_graphic_only_true_when_no_text_and_no_complete_box`
9. `test_graphic_only_false_when_a_complete_box_exists`：`0x79`…`0x7B` 上方、`0x7D`…`0x7E` 下方成对出现。
10. `test_graphic_only_false_when_any_text_tile_is_present`：任一图块 `>= 0x80` 即为假。

### 2.3 `pokemon_agent/world/items.py`（8 条）→ `tests/world/test_items.py`

1. `test_item_name_returns_table_name_for_known_id`：用 `tables/items.json` 里的一个真实 id 核对名字。
2. `test_item_name_writes_unknown_id_as_hex`：表外 id 写成 `ITEM_0x..`。
3. `test_item_id_round_trips_through_item_name`：`item_id(item_name(i)) == i`（取表中一个 id）。
4. `test_item_id_folds_case_and_accents`：大小写与 `é`/`e` 视同。
5. `test_item_id_returns_none_for_unknown_name`
6. `test_item_price_is_zero_for_the_hm_range`：`0xC4..0xC8` 为 0。
7. `test_item_price_is_none_for_tm_and_out_of_range_ids`：TM 与 `0` 或 `> LAST_REGULAR_ITEM` 为 `None`。
8. `test_item_price_decodes_bcd_from_rom`：构造 `ITEM_PRICES` 偏移处的三字节 BCD（如 `00 03 00` → `300`；注意 `00 30 00` 解码为 3000，不可用作 300 的例子），用假 ROM 字节。

### 2.4 `pokemon_agent/world/moves.py`（4 条）→ `tests/world/test_moves.py`

1. `test_move_name_returns_table_name_for_known_id`
2. `test_move_name_writes_unknown_id_as_hex`：`MOVE_0x..`。
3. `test_fold_uppercases_and_maps_accents`
4. `test_fold_collapses_whitespace_and_is_idempotent`

CP1 合计 **29 条**（7 + 10 + 8 + 4）。

## 三、CP2–CP5 范围（进入时再写用例）

- **CP2 场景与菜单**：`scene`、`scene_layout`、`screen_menu`、`priced_menu`、`battle_status`。
- **CP3 读数与对象**：`readout`、`object_events`、`terrain_sprites`、`map_tilesets`、`frame_encoding`、`task_perception`、`ram`（解码部分）、`tables/` 的 `warps.json` / `shop_layouts.json` / `pokecenter_layouts.json`。
- **CP4 `pyboy_world`**：只测调用模拟器之前的断言与构造检查（intent 第四节第 1 条列出的 4 类）。
- **CP5 迁移**：intent 第五节的 mcp 用例迁入，mcp 侧同时删除，同一条 CHANGELOG。

`screen_text` 已由 `tests/world/test_screen_text.py` 覆盖，不在 world 线的新增范围内。

## 四、验证（每个检查点）

- 新增用例全部通过，`ruff check` 与 `ruff format --check` 全绿。
- 破坏验证：每个模块挑一个生产函数做临时破坏，对应用例必须失败，还原后 `git diff pokemon_agent/` 为空。
- 默认 pytest 下 `tests/world/` 耗时 ≤ 5 秒。
- 全量 junit 计数 = 基线 + 本检查点新增条数。

## 五、CP1 的破坏验证点

| 模块 | 破坏方式 | 必须失败的用例 |
|---|---|---|
| `action_space.py` | 删 `assert entries, ...` | 第 6 条 |
| `screen_glyphs.py` | `title_logo` 的切片起点改为 `1:17` | 第 7 条 |
| `items.py` | `item_price` 的 HM 判断改为 `FIRST_HM < item` | 第 6 条 |
| `moves.py` | `fold` 删除 `é` 替换 | 第 3 条 |

## 六、CP2：场景与菜单（533，已探针核对）

依据：2026-10-18 在沙箱用真实模块（`pokemon_agent/world/` 源码，不起模拟器，内存为手写假件）逐条探针核对。下列每条断言都有探针结果；探针里的疑点写在“已知观察”，不钉成测试。

假件约定：`Mem` 为字典式内存（未写地址读 0）；屏幕 tile 由 `W_TILEMAP` 起始写入；文字用 `CHARMAP` 反查写入；菜单框内空白用 `0x7F`。

### 6.1 `pokemon_agent/world/scene.py` 与 `scene_layout.py`（8 个用例）→ `tests/world/test_world_scene.py`

1. `test_blank_screen_is_transition`：全屏 `0x7F`、不在战斗 → `TaskScene.TRANSITION`。
2. `test_title_logo_row_is_title_scene`：第 1 行第 2–17 列为 `0x80..0x8F` → `TaskScene.TITLE`。
3. `test_empty_start_frame_is_start_menu`：`(0,10)…(15,19)` 完整空框（角 `0x79/0x7B/0x7D/0x7E`，边 `0x7A`，侧 `0x7C`，内部 `0x7F`）→ `TaskScene.START_MENU`；`empty_menu_frame(tiles, 0, 10, 15)` 为真。
4. `test_alphabet_row_is_naming`：屏上有 `A B C D E F G H I` → `TaskScene.NAMING`。
5. `test_battle_menu_with_fight_cursor_is_battle_menu`：战斗中（`W_IS_IN_BATTLE=1`），2×2 战斗菜单，光标在 FIGHT → `TaskScene.BATTLE_MENU`。
6. `test_at_start_true_when_battle_cursor_on_fight`：同上帧，`at_start(text, BATTLE_MENU)` 为真。
7. `test_at_start_false_when_battle_cursor_on_item`：光标移到 ITEM，`at_start` 为假。
8. `test_at_start_refuses_a_normal_scene`：`at_start(text, TaskScene.WALK)` 触发 `AssertionError`（前置条件：仅开放脚本的场合）。

### 6.2 `pokemon_agent/world/screen_menu.py`（3 个用例）→ `tests/world/test_world_screen_menu.py`

9. `test_vertical_menu_reads_every_row_and_marks_cursor_cell`：竖排三项，光标在第一项 → `grid == [["POKEMON"], ["ITEM"], ["SAVE"]]`，`cell == (0, 0)`，`covered is True`。
10. `test_cursor_on_second_row_reports_that_cell`：同一框光标在第二项 → `cell == (1, 0)`。
11. `test_battle_menu_reads_a_two_by_two_grid`：战斗 2×2 → `read_screen_text(...).option_grid == [["FIGHT", "PKMN"], ["ITEM", "RUN"]]`。

### 6.3 `pokemon_agent/world/priced_menu.py`（4 个用例）→ `tests/world/test_world_priced_menu.py`

12. `test_no_money_title_returns_empty`：屏上没有 `MONEY` → `[]`。
13. `test_priced_box_returns_items_with_prices_and_cancel`：`MONEY ¥300` 屏，框内 `POTION` / `¥300`、`CANCEL` → `[("POTION", "¥300"), ("CANCEL", "")]`。
14. `test_single_item_box_is_refused`：框内只有一项 `CANCEL` → `[]`（`len(items) >= 2` 的判据）。
15. `test_border_tile_inside_box_is_refused`：价格框内某行的一格写入边框图块 `0x7D` → `[]`。

### 6.4 `pokemon_agent/world/battle_status.py`（4 个用例函数，展开参数后 9 项）→ `tests/world/test_world_battle_status.py`

16. `test_outside_battle_returns_none`：`W_IS_IN_BATTLE=0` → `read_battle_status(mem) is None`。
17. `test_reads_both_sides_names_levels_and_big_endian_hp`：我方 `PIKACHU`、等级 12、HP `0x0123`（291）、最大 `0x0140`（320）、状态 `0x08`；敌方 `RATTATA`、等级 3、HP 9、最大 20、状态 0 → 我方 `PSN`，敌方 `ok`。
18. `test_name_stops_at_terminator`：名字 `PIKACHU` 第 3 字节后写入 `NAME_END`，其后再写字符 → 名字 `"PIK"`。
19. `test_status_abbr_maps_each_status_bit`（参数化 6 项）：`0x00→ok`、`0x40→PAR`、`0x20→FRZ`、`0x10→BRN`、`0x08→PSN`、`0x07→SLP`。

CP2 合计 **19 个用例函数**，展开参数后 **24 个 pytest 项**（8 + 3 + 4 + 4 函数；`status_abbr` 参数化 6 项，故 +5）。

### 6.5 CP2 的破坏验证点

| 模块 | 破坏方式 | 必须失败的用例 |
|---|---|---|
| `scene.py` | 删掉 `if title_logo(tiles): return TaskScene.TITLE` | 第 2 条 |
| `scene.py` | `at_start` 的 `BATTLE_MENU` 判断去掉 `text.cursor == "FIGHT"` | 第 7 条 |
| `screen_menu.py` | 光标格判定 `(r, c) == (row0, col0 + 1)` 改为 `col0 + 2` | 第 9、10 条 |
| `priced_menu.py` | `if len(items) >= 2` 改为 `>= 1` | 第 14 条 |
| `battle_status.py` | `u16` 的高低字节顺序对调 | 第 17 条 |

### 6.6 CP2 已知观察（不写测试，不钉成预期，由设计侧裁决）

- 价格框内某行含光标字形 `0xED` 时，`read_priced_menu` 仍返回商品（探针 PR4：`POTION`/`¥300`/`CANCEL` 照常返回）。与第 15 条相比，只拒绝 `0x79–0x7E` 边框图块，光标字形不在拒绝集合内。是否应拒绝，待裁决。
