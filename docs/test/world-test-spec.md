# spec —— world 模块单元测试：契约与用例

> 依据：world 线 intent（项目文档 `claude/world-test-intent.md`，已确认）。
> 状态：CP1–CP4 已写到用例级；CP5 仍仅列范围，进入时再补用例。
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
- **CP3 读数与地形**：`readout`（`read_money`、`read_bag`、`read_party`）、`ram`（`read_facing`、`read_passable`）、`terrain_sprites`、`map_tilesets`、`frame_encoding`。`read_readout` 本轮不测（只做封装，断言价值由子函数承担）。
- **范围变更（2026-10-18，设计侧）**：`object_events`、`task_perception` 与 `tables/` 三张表（`warps.json`、`shop_layouts.json`、`pokecenter_layouts.json`）从 CP3 移至 CP4。理由：`object_events.py` 325 行、`task_perception.py` 75 行，表格的 `_source` 溯源字段尚未探针，都不是纯逻辑小模块，和 CP3 不同质。
- **CP4 `pyboy_world` 及其余**：入口前置断言、构造检查、`object_events`、`task_perception`、`tables/` 三张表与公开 `read_terrain` 精灵分类；精确范围见第八节。intent 四类原文未取得，不将候选归类冒充原文。
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

## 七、CP3：读数、地形精灵、地图表与帧编码（537，已探针核对）

假件沿用第六节开头。探针在沙箱 Python 3.11 venv 里对真实模块跑过，期望值全部是探针读出的结果，不是按源码推的。

### 7.1 `pokemon_agent/world/readout.py`（5 个用例函数，展开 7 项）→ `tests/world/test_world_readout.py`

- `test_money_is_three_byte_bcd`（参数化 3 项）：`12 34 56` → 123456；`00 30 00` → 3000；`00 03 00` → 300。
- `test_bag_stops_at_list_end`：件数写 3，第三项起始字节为 `0xFF`，读出 2 件 `(4, 5)`、`(10, 2)`。
- `test_bag_capped_at_capacity`：件数写 25，读出 20 件，末件 id 为 20。
- `test_party_reads_fields_for_count_only`：人数写 2，只读前 2 只。第一只 species 153、lv 12、HP 291/320、状态 `PSN`；第二只 species 37、lv 3、HP 9/20、状态 `ok`。
- `test_party_capped_at_six`：人数写 9，读出 6 只。

### 7.2 `pokemon_agent/world/ram.py` 解码（3 个用例函数，展开 6 项）→ `tests/world/test_world_ram_decode.py`

- `test_facing_from_sprite_byte`（参数化 4 项）：精灵表 +9 字节 0 / 4 / 8 / 12 → `south` / `north` / `west` / `east`。
- `test_passable_reads_list_until_ff`：从指针处读 `01 05 2C FF`，得 `{1, 5, 44}`。
- `test_passable_empty_list_asserts`：列表首字节即 `0xFF` → `AssertionError`。

`_sprite_kind` 是私有成员，不直接测，由 CP4 的 `read_terrain` 间接覆盖。

### 7.3 `pokemon_agent/world/terrain_sprites.py`（3 个用例函数，展开 4 项）→ `tests/world/test_world_terrain_sprites.py`

- `test_hidden_slots_flagged_only`：missable 表写 `(3, 7)`、`(5, 2)`、`0xFF` 终止；位图第 0 字节置 `0x80`，结果 `{3}`。
- `test_sprite_position_offset_minus_four`：槽 2 的原始 x=10、y=7 → `(6, 3)`。
- `test_sprite_slot_range_asserts`（参数化 2 项）：槽 0 与槽 16 → `AssertionError`。

### 7.4 `pokemon_agent/world/map_tilesets.py`（2 个用例函数）→ `tests/world/test_world_map_tilesets.py`

- `test_tilesets_indexed_by_map_id`：返回 `tuple`，长度 248，下标 `i` 与 `tables/map_tilesets.json` 的键 `str(i)` 逐项一致。
- `test_tilesets_cached_single_object`：两次调用返回同一对象（`lru_cache`）。

### 7.5 `pokemon_agent/world/frame_encoding.py`（2 个用例函数）→ `tests/world/test_world_frame_encoding.py`

- `test_png_data_uri_prefix_and_base64`：`b'\x89PNG\r\n'` → 前缀 `data:image/png;base64,`，后段 base64 解回原字节。
- `test_empty_png_still_prefixed`：空字节 → `data:image/png;base64,`。

### 7.6 CP3 合计

15 个用例函数，展开 21 项（7.1 为 7 项，7.2 为 6 项，7.3 为 4 项，7.4 为 2 项，7.5 为 2 项）。

### 7.7 CP3 的破坏验证点（5 处）

1. `readout.py` `read_money`：`(byte >> 4) * 10` 改为 `byte >> 4`，期望 `test_money_is_three_byte_bcd` 失败。
2. `readout.py` `read_bag`：去掉 `min(..., BAG_CAPACITY)`，期望 `test_bag_capped_at_capacity` 失败。
3. `ram.py` `FACING_BY_BYTE`：删去 `12: "east"`，期望 `test_facing_from_sprite_byte` 的对应参数失败。
4. `ram.py` `read_passable`：去掉 `if b == 0xFF: break`，期望 `test_passable_reads_list_until_ff` 失败。
5. `terrain_sprites.py` `sprite_position`：`- 4` 改为 `- 3`，期望 `test_sprite_position_offset_minus_four` 失败。

还原后 `pokemon_agent/` 应无改动。

### 7.8 CP3 已知观察（不写测试，不钉成预期，由设计侧裁决）

- `read_facing` 对未知字节（如 5）返回空串 `""`。这是“静默兜底”还是“应报错”，待裁决；本轮不把 `""` 钉成预期。
- `read_readout` 本轮不测；若要测，需在 CP4 前补探针确认其 `text_source` 与 `decoded` 字段。

## 八、CP4：物体事件、单帧装配、静态表与模拟器入口前置检查（545）

### 8.1 依据、范围与决定

- 实现基线：`934566d7efe3729021d900d7012f4e63fadb30c2`（CP3），父提交 `f14b41e`。
- 证据：主仓库未跟踪目录 `.coordination/world-cp4-probe/` 的 v1 探针及 v2 补证报告；
  v1 与 v2 冲突处以 v2 为准。设计侧已独立重跑，补证退出码 0，stdout/stderr 归一换行后完全一致。
  这些文件是本机证据，不是执行测试时的依赖；本节写齐输入与预期。
- intent 原文尚未取得。本节明确列出实际批准的范围，不把探针归纳的“四组”冒充 intent 的“四类”。
  `pyboy_world` 仅覆盖文件存在性、注册表一致性和依赖调用前的入口检查。
  `save_state` 非空是依赖调用后的检查，本轮不加；`read_wram` 两条已有用例不重复。
  `stop` 透传、`all_actions` 正常返回、推进帧数与模拟器行为不作为本轮新增用例。
- `read_terrain` 纳入 CP4，用公开返回的格网间接验证精灵分类，不直接调用 `_sprite_kind`。
- 只测试公开行为；手写假件。允许绕过 `PyBoyWorld.__init__` 注入假 pyboy 作为准备，
  但不调用/替换 `_tick` 等私有方法，不构造私有 `_Task`；已 reset 的样本通过公开
  `reset(..., start_state=b"\x00")` 准备，然后清空假件的调用记录。
  未 reset 样本仅将内部任务状态置空作为准备。断言只针对公开调用的结果与假件记录。
- 门+a 同格双事件是违反“按 place 唯一”后置条件的已确认现象；脚本会全量收集，
  step 路径只取首条。CP4 不修实现、不把重复输出写成正确预期、不添加以重复数为目标的测试。
  修复行为单独设计；不推断尚未验证的下游影响。
- 未知 facing 的 `KeyError`、`read_facing` 未知字节空串、价格框 `0xED` 行为仍待裁决。
  `read_readout` 不增独立测试；通过 `observe_task` 检查 decode 信封接线。
- 三张表不免除破坏验证：经公开常量验证装载结果，临时破坏 `scripts/tables.py`，
  不编辑 JSON，不直接测试私有装载函数。

### 8.2 通用假件与核验约定

- 地点用真实 `PlaceInWorld`。默认 actor=`(map12,x13,y8)`，north 邻格=`(12,13,7)`，
  north 两格外=`(12,13,6)`，east 邻格=`(12,14,8)`；跨图 after=`(1,13,7)`。
- `kind_at` 是按地点完整键查手写表的函数，未登记返回 `None`。
- 事件比较完整字典：公共五键为 `outcome/actor_place/place/object_kind/button`；
  dialog 加 `text`，warp 加目标 `map_id`；still 不带 text。不得只断言列表非空。
- 假内存未写地址读 0，同时支持整数和切片。tilemap 是 20×18，地形格网是 10×9。
  手写假 world 按顺序返回真实 `TaskPerceived/TaskObservation/Facts/Landmark`，记录 step 入参。
- 假 pyboy 记录 `load_state/button/tick`，tick 返回 True；只服务入口检查，绝不实例化真实 PyBoy。
  构造文件失败用 `tmp_path` 下确定不存在的路径；前置错误后不得有假件按键、tick 或读档调用。
- 各文件本地声明所需最小假件，不增加 conftest 或新的共用测试模块。遵守文件/函数行数限制。
  不用 MagicMock，不测私有函数，不读取 ROM 文件、不访问网络、不调真实模型。

### 8.3 物体事件 → `tests/world/test_world_object_events.py`

13 个函数，27 项。O 编号是用例引用号，不要求作为函数名。

| 编号 | 函数名 | 参数项数 | 输入与完整输出要求 |
|---|---|---:|---|
| O1 | `test_press_cells_returns_actor_and_facing_neighbor` | 4 | north/south/west/east 返回 actor 与对应邻格，依次为 (13,7)/(13,9)/(12,8)/(14,8)，map 均为12 |
| O2 | `test_interacting_with_person_records_dialog_or_still` | 2 | a、人@north邻格、同格after；“你好！”→唯一 dialog+原文，空白→唯一 still 无text |
| O3 | `test_counter_interaction_prefers_the_nearer_person` | 2 | a；仅两格外有人→事件地点(13,6)；邻格和两格外都有人→只出邻格(13,7)事件；dialog均“欢迎！” |
| O4 | `test_walking_into_item_records_dialog_or_still` | 2 | facing east、right、物@east邻格、after走到该格；“获得了 POKé BALL！”→dialog，空串→still |
| O5 | `test_a_key_does_not_pick_up_an_item` | 1 | a、物@north邻格、after同格→[] |
| O6 | `test_entering_door_waits_or_records_map_change` | 2 | north、up、门@north邻格；after停该格同图→[]；after跨图→唯一warp，目标map_id=1 |
| O7 | `test_pushing_from_door_records_warp_or_still` | 2 | actor=(12,13,7)，该脚下格为门，north/up；after跨图→warp目标1；after原格同图→still；事件place均(12,13,7) |
| O8 | `test_non_interactions_produce_no_events` | 6 | 分别为up连按2次、人@邻格；up先从south转向north、人@邻格；actor=None；after=None；b、人@邻格；up、石@邻格。其它字段用默认north、times=1、同格after、空dialog；均[] |
| O9 | `test_observe_step_reads_person_events_from_landmarks` | 2 | 真实landmark人@(12,13,7)，a，before/after同格；dialog“你好！”或空白→完整dialog/still；moved=False |
| O10 | `test_observe_step_reports_movement_and_item_event` | 1 | 真实landmark物@(12,14,8)，facing east、right、after进该格、拾取原文；moved=True且完整dialog事件 |
| O11 | `test_observe_step_ignores_stone_landmarks` | 1 | landmark石@north邻格，a，after同格、“推不动”→event=None，moved=False |
| O12 | `test_observe_step_chain_produces_no_event` | 1 | 两段[("up",1),("up",1)]、before/after同格→moved=False、event=None；world收到完整链 |
| O13 | `test_observe_step_forwards_settle_false` | 1 | 无landmark、a、before/after同格，settle=False→假world准确收到该键与False |

O2–O8 用公开 `judge_press`，O9–O13 用公开 `observe_step`。
O9/O10 的 before 使用真实 landmarks，而不是替换内部查询函数。
O8 的重复按键限制只声明已观察的方向键行为，不扩大成所有 a 连按也必须被拒绝。

### 8.4 地形精灵 → `tests/world/test_world_terrain_map.py`

3 个函数，3 项。碰撞表落点0xD800，内容01 05 2C FF；tilemap全01；
map12、玩家(13,8)、草图块FF、tileset0、sign/warp数量0。
精灵槽1/2/3/4/5的pic依次01/3D/3F/44/00；C2原始x/y依次
(17,12)/(18,12)/(15,10)/(22,12)/(9,9)。原始坐标减4后再投影到屏幕。
隐身表必须显式FF终止；需要隐藏槽1时写(slot1,index0)、FF，位图bit0置1。

| 编号 | 函数名 | 预期 |
|---|---|---|
| R1 | `test_terrain_places_visible_sprite_kinds` | cells共9行每行10列；cells[2]="..B......."；cells[4]="....NI...N"；其余全"."；pic0不产生标记 |
| R2 | `test_terrain_omits_hidden_sprite_slots` | 使用v1原始槽3坐标(10,12)并隐藏槽1：cells[4]=".....I...N"，其余行全"."（与已运行的v1隐藏样本一致） |
| R3 | `test_terrain_clips_sprites_outside_the_view` | 不隐藏；槽3改回原始(10,12)：全表无B，cells[4]="....NI...N"，其余全"." |

通过完整格网比较同时确认未凭空产生额外标记，不用测试私有分类函数。

### 8.5 单帧装配 → `tests/world/test_world_task_perception.py`

5 个函数，5 项。PNG素材用 `b"\x89PNG\r\n\x1a\nfake"`。
普通内存未写读0；terrain样本为9行"##########"、map12、玩家(13,8)、north、ambiguous0。
调用公开 `observe_task`，不替换其内部函数。

| 编号 | 函数名 | 输入与预期 |
|---|---|---|
| T1 | `test_unsettled_map_omits_location_and_terrain` | terrain=None、空ScreenText、closed=False：place=None、done=False、facts.where/facing/neighbors/walk_map为空、map_id=None、landmarks=[]，status="（这一帧只读了内存）地图尚未稳定。" |
| T2 | `test_task_perception_assembles_location_dialog_and_closed` | terrain样本、dialog“你好！”、options=["YES","NO"]、cursor="YES"、closed=True：place=(12,13,8)、done=True；facts字段逐项对应素材；neighbors="北 # 南 # 西 # 东 #"；status="（这一帧只读了内存）全局坐标 地图12 x=13 y=8，朝向 north。对话框：「你好！」。可选项：YES/ NO，光标在 YES" |
| T3 | `test_task_perception_wires_frame_and_decoded_readout` | 同T2但closed=False：frame_png等于公开png_data_uri(PNG)；ram.text_source="decode"，decoded三字段等于输入dialog/options/cursor |
| T4 | `test_task_perception_assembles_shop_items_view` | screen="┌─MONEY─┐\n▶BUY  SELL  QUIT"、options BUY/SELL/QUIT、cursor BUY、has_cursor=True；W_ITEM_LIST=2、后接4/5/FF；假ROM在0x4608+(id-1)*3写00 02 00/00 03 00：scene=SHOP_ITEMS，ShopItemsView依次POKé BALL 200/TOWN MAP 300、money=0、bag=[] |
| T5 | `test_task_perception_exposes_both_combatants` | CP2同款战斗内存+ScreenText(in_battle=True)：facts.scene=BATTLE；动态八键my_name=PIKACHU、my_level="12"、my_hp="291/320"、my_status=PSN、foe_name=RATTATA、foe_level="3"、foe_hp="9/20"、foe_status=ok |

T5名字与大端HP/状态输入沿spec6.4，名字写NAME_END。
不把全0 tilemap得到的 observation.scene=TRANSITION 冻结成战斗场景契约；
本条只断言 facts.scene 与八个战斗素材字段。无需重复CP2/CP3数值解码用例。

### 8.6 三张静态表 → `tests/world/test_world_tables.py`

4 个函数，11 项。只经 `scripts.tables` 的公开常量取数据，不调用 `_load_table`。

| 编号 | 函数名 | 参数项数 | 预期 |
|---|---|---:|---|
| D1 | `test_world_tables_keep_map_keys_and_provenance` | 3 | WARPS地图键={"12","40","41","42"}；SHOP={"42","56","67"}；CENTER={"41","58","64"}；三表_source/_note均为非空str；WARPS另有非空_coords/_indoor_source；不固定溯源文案、长度或字典顺序 |
| D2 | `test_known_warps_keep_door_and_edge_destinations` | 1 | 41/42的door_warps=[{x:3,y:7,dir:"down",to_map:1}]，40为[{x:4,y:11,dir:"down",to_map:0}]，均edge_exits=[]；12的size={w:10,h:18}、door_warps=[]，north/up→1 offset=-5与south/down→0 offset=0，两条trigger均step_off_edge |
| D3 | `test_service_layouts_keep_counter_standing_positions` | 6 | shop三图clerk={x:0,y:5,facing:"right"}、stand={x:2,y:5,facing:"west"}；center三图nurse={x:3,y:1,facing:"down"}、stand={x:3,y:3,facing:"north"}；shop的goods为非空列表，item非空str、price为int |
| D4 | `test_service_map_tilesets_match_their_layouts` | 1 | 公开map_tilesets()在42/56/67均为2，在41/58/64均为6 |

D2比较业务字段，不冻结name文案。三表地图键有交集41/42，不添加“互不相交”断言。
D3参数化为明确的6行，不在单次运行中动态生成pytest测试。
_source只保留非空溯源契约；此测试不声称独立验证其引用的ROM或外部项目。

### 8.7 模拟器入口前置检查 → `tests/world/test_world_pyboy_world_prechecks.py`

9 个函数，12 项。除P1/P2仅执行构造前文件检查，其余使用8.2的假pyboy实例。
setup通过公开reset准备的实例，在受测调用前清空假件button/tick/load记录；
失败路径确认记录仍为空，不观察生产私有状态作为测试结果。

| 编号 | 函数名 | 参数项数 | 预期 |
|---|---|---:|---|
| P1 | `test_missing_start_file_fails_before_simulator_construction` | 1 | rom与state_path均为tmp_path下不存在文件；FileNotFoundError包含“找不到存档”，证明存档检查先失败 |
| P2 | `test_missing_rom_fails_before_simulator_construction` | 1 | rom不存在、state_path=None；FileNotFoundError包含“找不到 ROM” |
| P3 | `test_reset_rejects_nonpositive_step_limits_before_loading` | 2 | max_steps=0/-1、start_state=b"\x00"→AssertionError匹配max_steps；无load/tick/button |
| P4 | `test_world_entries_require_reset_before_reading_or_acting` | 3 | 未reset分别调用step([("a",1)])、perceive_task()、get_action_space()→对应before reset断言；无依赖调用 |
| P5 | `test_step_rejects_a_closed_world_before_acting` | 1 | 准备closed=True的实例，step([("a",1)])→匹配window was closed；无button/tick |
| P6 | `test_step_validates_every_segment_before_any_button` | 1 | 已reset，step([("a",1),("nope",1)])→匹配unknown action；buttons/ticks均为空 |
| P7 | `test_evolve_rejects_negative_frames_before_ticking` | 1 | evolve(-1)→匹配negative frames，无tick |
| P8 | `test_load_state_rejects_empty_bytes_before_loading` | 1 | load_state(b"")→匹配empty bytes，无load/tick |
| P9 | `test_overlay_buttons_belong_to_the_world_namespace` | 1 | 公开OVERLAY_ACTIONS所有按钮集合⊆公开ALL_BUTTONS |

P1/P2为了保证即使回归也不触发真实模拟器，可用pytest monkeypatch将模块引用的PyBoy
绑定到会记录调用并立即抛显式异常的手写构造替身；断言替身零调用。
这属于公开入口依赖隔离，不直接测试生产私有成员，也不使用MagicMock。
这只是构造防护，不列为正式破坏验证点。
P5允许在准备阶段注入closed状态；不调用私有_tick制造该状态。

### 8.8 破坏验证（六处，逐个执行、逐个还原）

每次必须跑指定公开用例、记录实际失败节点和AssertionError正文；导入失败、语法错误、
收集错误或环境错误不算检出。使用独立进程避免模块缓存；还原后重跑目标测试。
临时破坏只允许下表涉及的生产文件，最后 `git diff -- pokemon_agent/` 必须为空。
禁止用git reset/checkout等还原，采用原始内容备份与精确还原。

| 模块 | 临时破坏 | 必须失败 |
|---|---|---|
| object_events | press_cells只返回[place]，去掉邻格 | O1四个朝向 |
| object_events | observe_step返回前把event设为None | O9的dialog/still |
| ram | _STILL_SPRITE_KIND的0x3F映射由BOULDER改为PERSON | R1 |
| task_perception | TaskObservation的done=closed改为done=False | T2 |
| scripts/tables | 公开WARPS装载语句临时改为WARPS={}，不改JSON | D1的WARPS参数 |
| pyboy_world | reset入口max_steps > 0改为max_steps >= 0 | P3的0参数 |

私有实现可以作为临时破坏点；测试仍只从公开入口观测结果。

### 8.9 数量、执行与验收

| 文件组 | 函数 | pytest项 |
|---|---:|---:|
| object_events | 13 | 27 |
| terrain_map | 3 | 3 |
| task_perception | 5 | 5 |
| tables | 4 | 11 |
| pyboy_world_prechecks | 9 | 12 |
| 合计 | 34 | 58 |

基线默认全量1517，world183；预期新增后默认全量1575、world241。
这些是设计计数，CHANGELOG的实测结果必须来自实际JUnit，不得把预期冒充运行结果。
继承第4节：failures/errors/skipped均0，world耗时≤5秒，Ruff check与format --check通过。

运行必须cwd=world-unit，使用主仓库.venv的python -m pytest，并先确认pokemon_agent.__file__
来自world-unit。脚本命令显式-X utf8；日志UTF-8捕获，stdout/stderr分开。
新增五个测试文件、CHANGELOG顶部一条（545）是唯一永久实现变更。
不得迁移mcp测试、不得改既有测试、不得增加共用假件文件；CP5另行处理。

## 九、CP5：mcp 迁移清单重新分类（561）

### 9.1 决定与依据

- 2026-10-20 设计侧核对 mcp 侧 9 条“待迁 world 线”用例，结论：它们断言的是服务端壳——信封
  `ok/code/data/events`、租约、`state_base64` 解码与转发——这些逻辑在
  `pokemon_agent/mcp_servers/world_server.py`，不在 `pokemon_agent/world/`。
  它们依赖的 world 侧逻辑（`moved` 判定、动作空间掩码、场景感知、脚本结算、读 WRAM、reset 起点）
  已由 CP1–CP4 与既有 `tests/world/` 覆盖，见 9.2。
- 用户裁决（选项 1）：**mcp 保留服务端契约，world 保留具体逻辑**。因此 CP5 不搬文件、不删用例、
  不改变任何用例的断言或节点名；字面迁移会让用例丢掉原本断言的内容，或迫使 `tests/world/`
  反向依赖 `mcp_servers`。
- `tests/mcpclient/world_tool/` 下的用例测的是客户端装配（`WorldMcpTool`），归“mcpclient 客户端装配（另案）”，
  不属于 world 线，本轮不动。
- 原 intent 的迁移清单与迁移时机据此作废；两份 intent 的相应段落在 CP5 提交时由设计侧同步，
  执行者不改任何文档。

### 9.2 逐条对应

| mcp 侧用例 | 去向 | 它在服务端壳钉住的 | world 侧对应覆盖 |
|---|---|---|---|
| `test_mcp_world_server.py::test_step_is_the_only_key_execution_gate_and_reports_moved` | 留 mcp | 段还原为 `(键名, 次数)` 元组、信封形状 | `test_world_object_events.py` O9–O13（`observe_step` 的 moved 与 event） |
| `…::test_step_reports_not_moved_when_the_world_did_not_move` | 留 mcp | `moved=False` 经信封返回 | O9 / O11 / O12 |
| `…::test_get_action_space_exposes_one_flat_namespace` | 留 mcp | `mask` / `entries` 信封形状 | `test_world_action_space.py::test_mask_covers_the_whole_namespace_with_keys_and_scripts`、`test_unavailable_key_is_listed_as_false_not_omitted` |
| `…::test_perceive_task_returns_the_memory_scene` | 留 mcp | 观测经信封返回 | `test_world_task_perception.py` T1–T5 |
| `…::test_reset_passes_start_state_only_when_supplied` | 留 mcp | base64 解码后转发、占租约 | `test_pyboy_world_state.py` 的 start_state / 空起点用例，`test_world_pyboy_world_prechecks.py` P3 |
| `…::test_read_wram_returns_the_world_bytes_base64` | 留 mcp | base64 线上编码逐字节还原 | `test_pyboy_world_state.py::test_read_wram_returns_only_the_wram_slice_without_ticking`、`test_read_wram_rejects_wrong_length` |
| `test_mcp_script_tools.py::test_walk_to_adjacent_forwarding` | 留 mcp | 参数转发、信封 `ok/code/data/events` 装配 | `tests/world/scripts/test_scripts_movement.py::test_walk_to_adjacent_open_ground` |
| `…::test_walk_to_adjacent_blocked_envelope` | 留 mcp | `blocked` 是合法结局码，不是传输错误 | `…::test_walk_to_adjacent_blocked_by_tree_or_npc` |
| `…::test_buy_item_end_to_end` | 留 mcp | 经 server 全链路的信封 | `tests/world/scripts/test_scripts_shop.py::test_buy_success` 及其失败路径用例 |

### 9.3 执行者改动（唯一的代码层改动，仅 docstring）

只改下列两个文件中的 docstring，不动函数名、参数、断言、夹具与导入：

- `tests/mcp_servers/test_mcp_world_server.py`：第 86、96、103、115、306 行去掉 docstring 开头的
  `【待迁 world 线】`（其后原文保留）；第 267 行 docstring 原文只有 `【待迁 world 线】`，
  改为 `start_state 只在传入时转发给 world（base64 解码），并占住租约。`
- `tests/mcp_servers/test_mcp_script_tools.py`：第 84、93、100 行去掉 docstring 开头的
  `【待迁 world 线】`。
- 行号以实际文件为准；改完后全仓 `tests/` 下不得再出现 `【待迁 world 线】`。
- `CHANGELOG.md` 顶部加一条，编号 561。除以上两个文件与 CHANGELOG 外，没有其他永久改动，
  不得改 `pokemon_agent/`、`docs/`、`.coordination/`。

### 9.4 验证

- 改动前后各做一次 `pytest --collect-only -q tests/mcp_servers`，节点 ID 集合逐字相同。
- 全量计数与基线一致：默认全量 1575、`tests/world` 241、`tests/mcp_servers` 不变，failures/errors/skipped 均 0。
- `git diff` 中每个变化行都在 docstring 内：只出现删去标注前缀的 docstring 行对，
  第 267 行是一行换一行。
- `git diff --stat` 只含上述两个测试文件与 `CHANGELOG.md`；`git diff -- pokemon_agent/` 为空。
- Ruff check 与 format --check 通过。本检查点没有生产代码改动，因此不做破坏验证。
- 所有入库文件行尾为 LF。
