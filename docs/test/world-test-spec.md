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
