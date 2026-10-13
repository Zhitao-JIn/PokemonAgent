# 交接：decoder 真值修补与 decoder 修复（2026-10-08）

> 给执行这项任务的 AI。先读 `AGENTS.md`，再读本文件。依据与证据见：
> - `docs/DECODER_TRUTH_AUDIT_1007.md`：审计报告（问题、地址、截图核对）。
> - `docs/DECODER_TRUTH_PATCH_1007.md`：补丁清单说明（人读版）。
> - `eval_results/labeling_1007/truth_patch_1007.json`：补丁清单（机器读，713 条操作）。
>
> 用户已认可审计结论和本文所有裁决，**不要再重新标注、不要重新采集 RAM、不要运行真实模型**。
> 审计里的路径 `evals/data/frames/...` 已在 (407) 迁移为 `evals/dataset/frames/v2/...`，内容哈希不变。

## 〇、目标与验收

**目标**：先把真值改成补丁清单的值，再修 decoder，使它在新真值上重新全部通过。

**验收（全部满足才算完成）**：

1. `evals/dataset/frames/v2/truth.jsonl` 应用了补丁清单的 713 条操作，每条应用前 `before` 与现值一致。
2. `python -m evals.dataset.frames.build.coverage`：`unaccounted_fields` 为空；`unresolved_fields` 只有 c-0109 的两项。
3. 13 字段通用基线（`scripts/decoder_baseline.py`）1045/1045；完整四组诊断（`decode` task，none 模型）scene/screen/takeover 各 1045 帧、terrain 适用帧全部为 C。（2026-10-12 注：基线脚本与旧 `decode` inspect task 将被 `python -m evals.single_state.decode` 取代，见 `docs/eval/eval-split-spec.md`。）
4. 相关已有测试通过，`ruff check . && ruff format .` 干净。
5. 每项一条 CHANGELOG（编号接 (407)，从 (408) 起），按 `AGENTS.md` 第三节第 6 条提交。
6. 第四节列出的 SPEC 与文档同步完成。

## 一、不可违反的约束

- 不改 `samples.jsonl`、截图、WRAM、存档；不改补丁清单以外的真值字段。
- 修 decoder 时**不许按 sample_id 分支**，也不许读真值或补丁清单来“对答案”。每条规则必须写成对任意帧都成立的判据。
- `world/` 出边为零（`scripts/check_world_self_contained.py` 必须通过）；新的地址常量放在使用它的模块，或 `ram.py`。
- 补丁里某条 `before` 与现值不符，立即停下并报告，不要猜。
- 规则在 1045 帧上通过了但你认为不对的，写进报告，不要私自改真值。

## 二、第一步：应用真值补丁

补丁文件格式（`format` 字段里也有）：

| op | 含义 |
|---|---|
| `set` | 把 `path` 处改成 `after`。`path` 为“组.键”，如 `screen_truth.options`；`takeover_truth.view.target` 是嵌套键；`unresolved_fields.terrain_truth.walk_map` 表示在 `unresolved_fields` 字典里新增键 `"terrain_truth.walk_map"` |
| `delete` | 删除该键 |
| `replace_group` | 整组替换为 `after`（13 个换图中间帧的 `terrain_truth` → `{}`） |

做法：

1. 先把现有 `truth.jsonl` 复制到 `eval_results/labeling_1007/truth_before_patch_1008.jsonl`。
2. 每条操作都带 `before`：`set` / `delete` / `replace_group` 核对现值相等；新增 unresolved 键的两条带 `expect_absent: true`，核对该键当前不存在。
3. 写一个一次性脚本逐条应用（脚本放 `eval_results/labeling_1007/`，不进 `evals/` 包），核对 `before`，保持原行顺序与 JSON 序列化风格（`ensure_ascii=False`）。
4. 应用后先跑 coverage 与 decoder 基线，**确认失败的帧与字段正好是补丁里那些**（期望：13 字段基线失败集中在 scene / options / option_grid / option_details / overlay / screen；四组诊断另有 terrain、takeover 失败）。把这份失败清单存到 `eval_results/labeling_1007/decoder_after_truth_patch_1008.json`，作为修复前基线。

注意：13 个换图中间帧的 `terrain_truth` 变成 `{}`，coverage 目前用“通行表指针非零”判地形是否适用，会把它们报成缺字段。这由第三节 C 项一起解决（共用同一个判据），不要用 unresolved 糊过去。

## 三、第二步：修 decoder（按此顺序，每项一条 CHANGELOG）

每项都给出：要改的位置、规则、受影响的帧（用于自查），以及已知陷阱。

### A / B / B2 / D：地形精灵层与草丛（`pokemon_agent/world/ram.py::read_terrain`）

- **隐藏物件（A）**：读 `wMissableObjectList`（0xD5CE，`(精灵槽号, 全局编号)` 成对，0xFF 结尾）和 `wMissableObjectFlags`（0xD5A6 起 32 字节位图，`flags[idx//8] >> (idx%8) & 1`）。位为 1 的精灵槽不进地形。
- **定位（B / B2）**：精灵所在格改用地图坐标：y = `mem[0xC204 + 16*i] - 4`，x = `mem[0xC205 + 16*i] - 4`，再按 `PLAYER_CELL` 与主角坐标换算，视野外丢弃。不再用 0xC1x4/0xC1x6 的屏幕像素。走动中的 NPC 自然落在目标格（游戏起步时已更新地图坐标），这是已认可的口径。
- **草丛（D）**：`wGrassTile`(0xD535) == 0xFF 表示本 tileset 没有草，此时不产生 `G`。
- 精灵种类判定（`_sprite_kind`）、招牌/门的写入顺序不变。
- 受影响：A 175 帧、A+D 3 帧、B 9 帧、B2 225 帧（清单 `issue` 字段可查）。c-0109 地形已改为 unresolved，不参与比对。

### C：换图中间帧（`world` + `evals/dataset/frames/snapshot.py` + `coverage.py`）

- 现象：`wCurMap`(0xD35E) 已切到目标图，`wCurMapTileset`(0xD367)、碰撞表指针、`wTileMap`、坐标还是来源图。
- **判据**：地图头里的 tileset ≠ `wCurMapTileset`。地图头 tileset 来自 ROM：`MapHeaderPointers` 0x01AE（每图 2 字节小端）、`MapHeaderBanks` 0xC23D（每图 1 字节），头部第一字节即 tileset。
  `world` 运行时不读 ROM，所以**从 ROM 一次性生成静态表** `pokemon_agent/world/tables/map_tilesets.json`（地图编号 → tileset），与 `items.json`、`moves.json` 同法；在 `ram.py` 暴露一个判据函数（例如 `map_settled(mem) -> bool`：通行表指针非零且表中 tileset 与 0xD367 相等）。
- **用法**：
  1. `scene.py`：地图已载入但未稳定、且屏幕无字（这 13 帧 `screen` 都为空）→ `TRANSITION`。
  2. `evals/dataset/frames/snapshot.py::has_map` 与 `build/coverage.py` 的 `map_loaded` 改用同一判据，未稳定的帧地形不适用。
  3. 生产链路（`pyboy_world.py` 读地形处）在未稳定时不得输出“目标图编号 + 来源图坐标”的地点。具体做法（跳过地形、或沿用上一稳定帧）由你定，写进 SPEC。
- 受影响：c-0087、c-0091、c-0268、c-0273、c-0391、c-0472、c-0482、c-0487、c-0527、c-0534、c-0539、c-0541、c-0703。
- 自查：生成表后核对 1032 个地图已载入的帧，除这 13 帧外表值与 0xD367 全部相等。

### E：昵称键盘（`pokemon_agent/world/scripts/scenes/naming.py`）

- `target` 改由 `wNamingScreenType`(0xD07D) 决定：0 → `YOUR NAME?`，1 → `RIVAL's NAME?`，≥2 → `NICKNAME?`（屏幕第 3 行 (3,1)–(3,9) 的字，可用来核对）。
- 长度上限同样按 0xD07D：≥2 为 10，否则 7（ROM 0x66AE 处 `cp 2 / cp $0A` 证实）。删掉按标题文字查表的 `MAX_LENGTH`。
- 受影响：c-0198–c-0203、c-0663–c-0668。玩家/对手命名帧的 target 不得改变。

### F：战斗招式空位（`screen_menu.py` 或 `screen_layout.py`）

- 战斗招式框（屏幕 (12,4) 起的框、`in_battle`）里文字恰为 `-` 的行不是选项：从 `options` / `option_grid` / `option_details` 中去掉，仍留在 `screen`。光标格不变（空位总在已学招式之后）。
- 依据：`wMaxMenuItem` = 招式数 + 1，ROM 0x3D3C9 / 0x3D3DD 把光标回绕在 1…招式数，空位不可达。
- 命名键盘里的 `-` 键是真键，不能被这条规则误伤。
- 受影响：c-0239、c-0240、c-0256、c-0257、c-0455、c-0623、c-0642、c-0643、c-0675、c-0779、c-0780、c-0781、c-0875、c-0891、p-move_list、p-move_list_2。

### H：无箭头完整商品框（`pokemon_agent/world/priced_menu.py`）

- 允许框内**最后一项**为无价格的 `CANCEL`；其余项仍须有完整价格，遮挡、残框仍返回空表。
- 受影响：c-0493、c-0589（期望 4 个选项、附注 `['¥100','¥200','¥250','']`、`overlay=choice`）。c-0492、c-0497 结果不得改变。

### I：0xFF 黑块（`screen_text.py` 渲染 + `scene.py`）

- **渲染**：图块 0xFF 只有在左右至少一个相邻图块是字表图块（0x7F 空格、0x80–0xFE 文字/数字/符号、0x79–0x7E 边框）时才渲成 `9`，否则按非文字图块渲成 `·`。审计已在 1045 帧上核对：擦除帧（c-0225 98 个、c-0226 238 个、c-0467 108 个、c-0766 360 个）全部没有字表邻居，而所有真实数字 9 都有。
- **场合**：屏幕上“无字表邻居的 0xFF”≥ 20 个 → `TRANSITION`（放在战斗分支之前）。受影响 c-0467（`battle` → `transition`）。
- 受影响的 screen：c-0225、c-0226、c-0467、c-0766（四帧渲染后整屏为空串）。

### J：标题与版权页（`screen_text.py` / `scene.py`）

- 标题待机页：第 1 行第 2–17 列为 0x80…0x8F 连续序列（Logo）时，`scene=title`，整屏 `screen` 为空串。受影响 c-0009、c-0010、c-0011。
- 版权页 c-0003、c-0004、c-0005：期望 `screen` 为空串（Logo 图块被误渲成 `ID`、`└`、`─`）。判据自行设计（例如屏上没有任何字母图块 0x80–0xB9、也没有完整的框），必须在 1045 帧上不误伤其它帧。

### K：场合边界（`pokemon_agent/world/scene.py`）

- 战斗中出现能力页（`STATUS/`、`TYPE1/`、`EXP POINTS`）或图鉴条目页 → `pokemon_info`，判定放在战斗分支之前。受影响 c-0247、c-0248、c-0249、c-0659。
  陷阱：c-0659 的 `No.` 在战斗里目前不渲染（`·.016`），`_dex_entry` 认不出；先做 M 项的 `№` 渲染，或改用不依赖 `No.` 的特征。
- 野外背包大框已画但列表为空（与 `has_battle_menu_frame` 的大框同一形状，背后是开始菜单）→ `bag`，`at_start=false`，接管视图照常给出（背包 + 队伍）。受影响 c-0440。
- 开始菜单框已画但条目为空 → `start_menu`。受影响 c-0419。
- 不得改变其它帧的场合（尤其 c-0420、c-0434、c-0952 这几帧有框有字或有空心箭头，现值正确）。

### L：`covered`（`pokemon_agent/world/screen_layout.py`）

- 队伍列表与图鉴列表的 `covered` 输出改为 `true`。
- **陷阱**：`_layout(..., covered)` 的 `covered` 参数同时参与光标匹配（`column == ac + 1 or not covered`），图鉴列表的箭头在第 0 列、选项在第 4 列，直接改参数会丢光标。须把“输出的 covered”和“光标是否必须紧贴选项”拆成两个参数。
- 受影响 26 帧（清单 `issue=L`）。

### M：渲染细节（`screen_text.py::render_screen` / `_hud_positions`）

- 命名键盘布局（`is_keyboard` 为真）下，图块 0x76（空名字槽）与 0x77（当前位置）渲成 `_`，不再当战斗 HUD 框线渲成 `─`/`┘`。只作用于该布局，战斗 HUD 不变。
- `№`（0x74）后紧跟 `<DOT>`（0xF2）时渲成 `No`（加上后面的 `.` 即 `No.`）；该组合在战斗中也按此渲染（战斗 HUD 不会出现 0x74+0xF2）。0x74 后直接接数字时维持现状。
- 受影响 40 帧（30 个命名帧、c-0149–c-0153、p-stats_page、c-0247、c-0248、c-0249、c-0659）。

## 四、第三步：同步文档

- `docs/spec/world/SPEC.md`：精灵定位与隐藏物件、换图中间帧判据与生产处理、0xFF 渲染、标题判据、场合边界、命名 target 与长度、`covered` 含义、名字槽与 `№` 渲染。
- `docs/spec/evals/SPEC.md`：真值修补记录、`has_map`/coverage 的新适用判据、c-0109 unresolved。
- `docs/DECODER_RELABEL_1007.md`：在“最新标注规则”里标注已被本次裁决替代的条目（“重复 `-` 按物理位置记录” → 空位不是选项；命名键盘 9/9/8/9/9 维持，并注明第 3 行第 9 格是可输入的空格键、刻意不提供）。
- `docs/DECODER_FIX_1007.md`：追加一节“2026-10-08 真值修补后复修”，给出前后结果与报告路径。
- 不改 `docs/DECODER_TRUTH_AUDIT_1007.md` 与 `docs/DECODER_TRUTH_PATCH_1007.md` 的结论；可修正其中的旧路径。

## 五、第四步：验证与报告

1. 重跑 13 字段基线，输出 `eval_results/labeling_1007/decoder_final_1008.json`（`--previous` 用第二节第 4 步的文件），确认 fixed 列表覆盖全部受影响帧、regressed 为空。（2026-10-12 注：基线脚本将被取代，见 `docs/eval/eval-split-spec.md`。）
2. 跑完整四组诊断（`python -m evals run decode --log-dir eval_results/labeling_1007/inspect_decoder_1008`，none 模型）。（2026-10-12 注：该命令将被 `python -m evals.single_state.decode` 取代，见 `docs/eval/eval-split-spec.md`。）
3. 跑相关测试：读屏、场合、地形、接管视图、命名脚本、`tests/test_evals_perceive.py` 等现有文件；把本次修正的代表帧加进**现有**测试文件的回归用例（每项至少一帧），不新建测试文件。
4. `python scripts/check_world_self_contained.py`。
5. 最后向用户报告：每项改了什么、前后数字、未能满足的验收项（如有）及原因。

## 六、已知局限（照实写进报告，不要试图在本任务里解决）

- 这 1045 帧既用于定位问题又用于验证修复，结果仍不是留出集上的泛化结论。
- 没有模拟器实测：建议后续实测“走到原幽灵格”“输入 10 字母昵称”“进出门”三件事。
- 样本未覆盖的情形见审计报告第六节（小写键盘、带异常状态或 3 只以上的队伍、非空 PC 箱、忘招列表等）。
