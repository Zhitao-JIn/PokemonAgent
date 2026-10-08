# decoder 真值独立审计（2026-10-07）

> 范围：`evals/dataset/frames/v2/samples.jsonl` 1045 帧 × `evals/dataset/frames/v2/truth.jsonl`（审计时位于 `evals/data/frames/`，(407) 迁移，内容哈希不变） 全部四组字段。
> 本报告只提交问题与证据，**未修改真值、decoder、样本、截图、RAM 或存档，未运行真实模型，未提交/推送**。

## 一、结论摘要

全量自动比对“真值 = decoder”只证明两者一致。本次从冻结 WRAM 与 ROM 出发独立复算后，
**没有发现“真值单独错、decoder 单独对”或反过来的情况**：凡是找到的错误，真值与 decoder 都错在同一处
（真值的生成逻辑与 decoder 的实现同源或同一假设）。下列问题按对下一步动作的影响排序。

| # | 问题 | 字段 | 帧数 | 性质 | 影响下一步动作 |
|---|---|---|---:|---|---|
| A | 已隐藏的 missable 物件（被拿走的球、退场的 NPC）仍画成 `I` / `N` | terrain.walk_map / neighbors | 177（其中 113 帧四邻改变） | 两者共同错误 | **是**：把可走格判成“人/物”，或把桌子判成“物” |
| B | 刚换图、精灵屏幕坐标尚未刷新（=0,0）时全部堆到 (0,0) 格 | terrain.walk_map | 13 | 两者共同错误 | 低（不在四邻，但地形图出现幽灵 NPC/物品） |
| C | 换图中间帧：地图编号已切到目标图，坐标、图块、碰撞表仍是来源图 | terrain.map_id / where / walk_map；scene | 13 | 两者共同错误 | 中（记忆键 `map:x:y` 被写成错误地点） |
| D | 室内 tileset 的 `wGrassTile=0xFF`（无草），但图块 0xFF（黑块、数字 `9`）被判成草 `G` | terrain.walk_map | 3 | 两者共同错误 | 低 |
| E | 宝可梦昵称键盘的 `target` 取成第一行“种名+图标”，而非 `NICKNAME?`；连带脚本把昵称上限从 10 算成 7 | takeover.view.target（及脚本行为） | 12 | 两者共同错误 | **是**：8–10 字昵称会被 `naming_enter_name` 误拒 |
| F | 战斗招式框的空位 `-` 被列为选项，实际光标到不了 | options / option_grid | 16 | 与现行规则一致，与 ROM 行为不符，需裁决 | 中（模型可能选 `-`） |
| G | 命名键盘第 3 行第 9 格是可输入的空格键，真值只记 8 项 | options / option_grid | 30 | 与现行规则一致，与 ROM 行为不符，需裁决 | 低 |
| H | 无箭头、滚动到底（含 CANCEL）的完整商品价格框未给选项，与“无箭头完整价格框仍有选项”规则不一致 | options / option_grid / option_details / overlay | 2 | 两者共同错误 | 低 |
| I | 0xFF 黑块被渲成数字 `9`；c-0467 因此被判 `battle` 而非 `transition` | screen；scene | 4 | 两者共同错误 | 低–中 |
| J | 标题画面（Logo + Red Version，等按 START）被判 `transition`，整屏把 Logo 图块渲成字母 | scene / screen | 3（另 3 帧版权页只涉 screen） | 两者共同错误 | 低（生产范围外） |
| K | 场合边界：战斗中的能力页、图鉴条目页判 `battle`；空列表框在野外判 `transition`、在战斗判 `battle_menu` | scene | 6 | 暂无法确定，需裁决 | 低 |
| L | 已完整解出的队伍列表、图鉴列表 `covered=false` | covered | 26 | 契约问题，需裁决 | 低（会触发“切分不全”提示） |
| M | 渲染细节：命名下划线槽渲成 `┘──────`；`№`+`.` 渲成 `No..001` | screen | 30 + 6 | 两者共同（契约渲染） | 很低 |

13 字段通用基线（scene … screen）中真正受影响的只有 **F、G、H 的 options/option_grid/option_details/overlay、I/J 的 scene/screen、K 的 scene**；
A–E 落在基线之外（terrain、takeover），但 A、E 对动作的影响最大。

## 二、检查方法与独立性

1. **只用原始材料**：冻结 WRAM（0xC000–0xDFFF，已核对每帧 `tiles` 与 `wTileMap`(0xC3A0) 逐字节相同，1045/1045）、
   ROM（`assets/rom`，SHA1 `ea9bcae6…8b9a` = 英文红版）。名称表从 ROM 直接取：种族名 0x1C21E、招式名 0xB0000、道具名 0x472B、价格 0x4608。
2. **自写参考实现**（未 import 仓库代码，未用 `label` 预标，未用 decoder 输出）：字表、整屏渲染、对话、叠加层、
   商品/背包列表、业务视图、地形全部按 pokered 内存布局独立重写，再与真值比较；比较一致的部分说明真值符合“现行契约”，
   不一致的部分再看 ROM 代码、RAM 状态和截图。
3. **契约之外看游戏行为**：用菜单状态变量交叉核对光标（`wMenuCursorLocation` 0xCC30、`wCurrentMenuItem` 0xCC26、
   `wMaxMenuItem` 0xCC28、`wListScrollOffset` 0xCC36、`wListPointer` 0xCF8B），反汇编确认三处关键行为
   （命名键盘输入 0x66AE、招式光标回绕 0x3D3C9 / 0x3D3DD）。
4. **截图只作辅助**：共目视约 30 帧截图（拼图核对），截图与 RAM 冲突时以 RAM 为准；本报告所有“确认”结论都有 RAM 证据，
   截图仅作佐证。
5. **未重跑 decoder**：decoder 与真值的一致性引用 `DECODER_FIX_1007.md`（1045/1045）；我的契约复现实现与真值逐帧完全一致
   （见第三节），因此下列共同错误同样存在于 decoder。

## 三、独立复算后确认一致的部分（不是问题）

| 检查 | 范围 | 结果 |
|---|---|---|
| `tiles` = WRAM `wTileMap` | 1045 帧 | 1045 一致 |
| `screen`（按 SPEC 契约独立实现渲染） | 1045 帧 | 1045 一致（契约本身的问题见 I、J、M） |
| `dialog_text`（底部框 + 图鉴说明框） | 1045 帧 | 1045 一致 |
| `quantity_box` / `strict_dialog` / `overlay` | 1045 帧 | 1045 一致（H 两帧随选项连带） |
| `has_cursor`、`cursor_cell`↔实心箭头、`in_battle`↔`wIsInBattle`(0xD057) | 1045 帧 | 全部一致 |
| 实心箭头位置 = `wMenuCursorLocation` | 169 帧有选项/光标 | 169 一致 |
| 列表菜单（商店买/卖、背包、战斗背包、PC 取物）可见项与光标 = `wListPointer` 数据 + `wListScrollOffset` + `wCurrentMenuItem` | 38 帧 | 38 一致 |
| `option_details`：价格 = ROM `ItemPrices`，数量 = 背包/PC RAM，重要道具不显示数量 | 143 个选项附注（含空串） | 143 一致 |
| `covered_by_script` = 场合 ∈ 八个仅开放脚本的场合；`at_start` 是否为 null | 1045 帧 | 全部一致 |
| 业务视图：队伍（0xD16B/0xD2B5）、背包（0xD31D）、金钱（0xD347 BCD）、商品（0xCF7B）、战斗双方（0xD009/0xD014、0xCFDA/0xCFE5）、`trainer`、学招（0xCF92/0xD0E0）、PC 道具（0xD53A）、箱号（0xD5A0） | 241 帧有视图 | 数值全部一致；战斗中在场宝可梦的 HP/PP 在队伍结构与 `wBattleMon` 两处一致；`active` = `wPlayerMonNumber`(0xCC2F) 一致 |
| terrain `map_id` / `where` / `facing`(0xC109) / `neighbors` 与 walk_map 自洽 | 1032 帧 | 全部一致（内容错误见 A–D） |
| 地形碰撞：ROM 碰撞表（`wTilesetCollisionPtr` 0xD530，bank 0）、左下子图块、warp(0xD3AE)、sign(0xD4B0)、台阶图块 | 1032 帧 | 不考虑精灵隐藏时与真值逐格一致；精灵层问题见 A–C |
| `at_start`：战斗主菜单须四项完整且光标在 FIGHT；其它场合按各自主菜单 | 241 帧仅开放脚本的场合 | 全部符合现行规则 |
| 子菜单不从背景借 `CANCEL`（c-0427、c-0438、c-0972、p-field_party_sub、p-battle_party_sub、p-pc_deposit_sub） | 6 组 | 正确 |
| 队伍列表名字在箭头上一行、主动/倒下换人统一为 `battle_switch` | 26 帧 | 正确；倒下换人帧 `FNT` 与等级并存，未丢选项 |
| 设置页只取实心箭头所在行、图鉴列表保留 `----------` 占位 | c-0942、p-option_screen；c-0423、c-0948–c-0951 | 符合裁决（光标、行列与 RAM 一致） |
| 商店：数量框遮挡时不补造列表、无箭头不猜光标 | c-0491、c-0503–c-0510、c-0519–c-0522、c-0547–c-0553、c-0580–c-0581、c-0590–c-0592、p-shop_qty_*、p-shop_confirm、p-shop_after 等 | 正确 |

## 四、问题清单

### A. 已隐藏的 missable 物件仍画进地形图（两者共同错误，影响动作）

- **字段**：`terrain_truth.walk_map`、`terrain_truth.neighbors`。
- **帧**：177 帧（附录 1），其中 113 帧四邻改变（附录 2）。集中在大木研究所（map 40）、小茂家（39）、真新镇（0）。
- **证据**：红版用 `wMissableObjectList`(0xD5CE，`(精灵号, 全局编号)` 对，0xFF 结尾) + `wMissableObjectFlags`(0xD5A6 位图) 标记被隐藏的物件；
  标志位为 1 的精灵不显示、不占格。真值/decoder 只看精灵图片号（0xC1x0），不看隐藏标志。
- **代表帧**：

| 帧 | 隐藏的精灵 | 当前真值 | 正确值 | 截图 |
|---|---|---|---|---|
| c-0272（walk，真新镇） | 1（开场的大木） | neighbors `北 . 南 . 西 . 东 N`；第 4 行 `N...@N....` | `东 .`；`N...@.....` | 主角右侧无人 |
| c-0261（walk，研究所） | 2、4（两颗已被拿走的球）、8（第二个大木） | `南 N`；第 1 行 `.....III.#`；第 5 行 `###.N#####` | `南 .`；`.....#I#.#`；`###..#####` | 桌上只剩一颗球，主角南侧无人 |
| c-0228（battle，研究所对战） | 2、4、8 | `北 N 南 N 西 # 东 #` | `北 N 南 # 西 # 东 #` | — |
| c-0156（dialog，刚选完妙蛙种子） | 4、8 | `北 I` | `北 #`（桌子） | 主角正上方的球已消失 |
| c-0416（dialog，小茂家拿到城镇地图） | 2、3 | 第 3 行 `N#..NI#...` | `##..N##...` | 桌上无物 |
| c-0116（walk） | 8 | `北 N` | `北 .` | 主角正上方无人 |

- **对动作的影响**：`neighbors` 直接进入 task 层地形提示，主角会被告知“东边有人/北边有物”而绕路或去按 A 对话；
  走到“幽灵 I”格还会被记忆层当成可拾取物。113 帧的四邻因此不对。

### B. 换图首帧精灵屏幕坐标为 (0,0) 时堆在左上角（两者共同错误）

- **字段**：`walk_map`。
- **帧**：c-0113、c-0114、c-0326、c-0350、c-0371、c-0392、c-0413、c-0471、c-0473、c-0534、c-0541、c-0683、c-0707。
- **证据**：这些帧多个精灵的屏幕坐标（0xC1x4 y、0xC1x6 x）都是 0（换图后还没刷新），decoder 以 `x//16, (y+4)//16` 换算全部落在格 (0,0)，
  最后写入者胜出，于是 (0,0) 出现 `N` 或 `I`（如 c-0113 第 0 行 `I##.N#####`）。截图 c-0113、c-0392 左上是书架，c-0471 是树、c-0707 是黑边，均无人/物。
- **正确值**：(0,0) 应按图块通行性给出（`#` 或 `.`），且这些精灵应按地图坐标（0xC2x4/0xC2x5 −4）或隐藏标志处理。
- **影响**：(0,0) 不是四邻，`neighbors` 不受影响；地形图里出现幽灵 NPC/物品，可能误导绕行规划与记忆。

### B′. 走动中 NPC 的格子取整（暂无法确定，建议复核）

- 293 帧中有可见精灵的屏幕坐标不在 16 像素网格上（NPC 或镜头在移动中）。真值按向下取整定格，有时与地图坐标及截图不符：
  c-0099 大木 x=45 → 真值第 7 行 `##N...####`（列 2），地图坐标（9,4→列 3）与截图都在列 3；c-0088 妈妈 y=90 → 真值第 5 行，地图坐标与截图在第 6 行。
- 另有 c-0109 等帧截图与 RAM 不同刻，无法裁定。**暂不认定为错误**，但建议裁定“移动中的精灵占哪一格”（取整方式或改用地图坐标）。

### C. 换图中间帧：地图编号与坐标/画面不同步（两者共同错误）

- **字段**：`terrain_truth.map_id`、`where`、`walk_map`；`scene_truth.scene`（这些帧都标 `walk`，c-0527/c-0539 标 `shop`）。
- **帧（13）**：c-0087、c-0091、c-0268、c-0273、c-0391、c-0472、c-0482、c-0487、c-0527、c-0534、c-0539、c-0541、c-0703。
- **证据**：`wCurMap`(0xD35E) 已是目标图，但 `wCurMapTileset`(0xD367)、碰撞表指针(0xD530)、`wTileMap` 和坐标(0xD361/0xD362) 仍属来源图；
  用 ROM 地图头（`MapHeaderPointers` 0x01AE / `MapHeaderBanks` 0xC23D）第一字节核对，13 帧的 tileset 均与 `wCurMap` 不符。
  例：c-0273 真值 `where=全局坐标 地图37 x=5 y=5`，但 (5,5) 是真新镇（地图 0）里主角家门口的坐标，画面也仍是真新镇（截图确认）；
  c-0391 `地图40 x=12 y=11` 是真新镇里研究所门口坐标；c-0703 `地图50 x=3 y=43` 是 1 号道路坐标。
- **正确值**：这些帧的地点应标为来源图（上一帧的 map_id）+ 当前坐标，或把整帧标为过场（地形不适用/未定）；**不能**输出“目标图编号 + 来源图坐标”的组合。
- **影响**：动作上影响小（换图期间按键无效），但 `PlaceInWorld.key` 会写出不存在的地点，污染记忆与交互判定。

### D. 无草 tileset 把图块 0xFF 判成草（两者共同错误）

- **字段**：`walk_map`、`neighbors`。
- **帧**：c-0225、c-0226（研究所进入对战时的黑色擦除，0xFF 黑块被画成整列 `G`）；c-0257（招式框 PP `29/35` 中的数字 `9` = 图块 0xFF，第 5 行出现 `###GN#####`）。
- **证据**：室内 tileset 的 `wGrassTile`(0xD535) = 0xFF，是“无草”哨兵；真值/decoder 直接拿它与图块比较。
- **正确值**：`wGrassTile=0xFF` 时不应产生 `G`；c-0225/c-0226 的擦除区应为不可判定或 `#`，c-0257 第 5 行列 3 应为 `#`。
- **影响**：低（过场/菜单帧），但会让“研究所里有草丛”进入记忆。

### E. 昵称键盘的 target 与长度上限（两者共同错误，影响脚本）

- **字段**：`takeover_truth.view.target`。
- **帧（12）**：c-0198–c-0203（BULBASAUR）、c-0663–c-0668（PIDGEY）。
- **当前真值**：`target = "BULBASAUR ·"` / `"PIDGEY ·"`（取了整屏第一行：种族名 + 宝可梦小图标图块 0xC9）。
- **正确值**：本页提示是第 3 行 `NICKNAME?`（图块 (3,1)–(3,9) = `8D 88 82 8A 8D 80 8C 84 E6`），截图确认；
  `wNamingScreenType`(0xD07D) = 2（宝可梦），而玩家/对手命名页为 0/1。
- **ROM 证据**：命名输入例程 0x66AE 处 `ld a,[$D07D]; cp 2; jr nc …; ld a,[$CEE9]; cp $0A` —— 宝可梦昵称上限 10，人名上限 7。
- **影响**：脚本 `naming_enter_name` 以 `MAX_LENGTH.get(_title(screen))` 求上限，键是 `"NICKNAME?"`，而 `_title` 取到 `"BULBASAUR ·"`，
  于是昵称上限退回 7，8–10 字母的昵称会被 `invalid_name` 误拒；模型看到的 target 也带一个无意义的 `·`。

### F. 战斗招式空位 `-` 不可选（与现行规则一致，与 ROM 行为不符，需裁决）

- **字段**：`options`、`option_grid`（`option_details` 长度随之变化）。
- **帧（16）**：c-0239、c-0240、c-0256、c-0257、c-0455、c-0623、c-0642、c-0643、c-0675、c-0779、c-0780、c-0781、c-0875、c-0891、p-move_list、p-move_list_2。
- **当前真值**：如 c-0239 `[['TACKLE'],['GROWL'],['-'],['-']]`。
- **ROM/RAM 证据**：`wMaxMenuItem`(0xCC28) = 招式数 + 1（c-0239 两招为 3、c-0675 三招为 4），项号从 1 开始（第 13 行 = 第 1 招）；
  `SelectMenuItem_CursorUp`（0x3D3C9）在项号 0 时跳到 `wNumMovesMinusOne`(0xCD6C)+1，`SelectMenuItem_CursorDown`（0x3D3DD）在项号 = 招式数 + 1 时回到 1。
  光标只能停在 1…招式数，空位 `-` 永远到不了。
- **建议值**：`options` 只含已学招式（c-0239 为 `TACKLE, GROWL`），`-` 只留在 `screen`。
- **说明**：`DECODER_RELABEL_1007.md` 已规定“`-` 独立占一行、重复 `-` 按物理位置记录”，本条与该规则冲突，请用户裁决。
- **影响**：中。模型若照选项选 `-`，`battle_fight` 会以 `unknown_move` 拒绝，浪费一步。

### G. 命名键盘空格键（与现行规则一致，与 ROM 行为不符，需裁决）

- **字段**：`options`、`option_grid`（行宽 9/9/8/9/9）。
- **帧（30）**：全部 `naming` 帧（附录 3）。
- **ROM 证据**：大写键盘字串在 0x67D6：`ABCDEFGHIJKLMNOPQRSTUVWXYZ ×():;[]PKMN-?!♂♀/.,¥lower case`，第 27 个字符就是空格（0x7F），对应第 3 行第 9 格
  （图块 (9,18)）；输入例程 0x66AE 把光标右侧图块原样追加进名字（只对 0xE4/0xE5 做浊点特殊处理），没有过滤 0x7F。
  因此该格可停光标、按 A 会输入空格。
- **建议值**：第 3 行为 9 项（第 9 项为空格键，可记作 `SPACE` 之类的显式名）；`lower case` 按用户裁决仍不计入。
- **影响**：低。脚本按 RAM 光标坐标导航且只输入大写字母，不依赖该格。

### H. 无箭头的完整商品框在滚动到底时没有选项（两者共同错误）

- **字段**：`options`、`option_grid`、`option_details`、`overlay`。
- **帧**：c-0493、c-0589。
- **当前真值**：`options=[]`、`overlay=none`。
- **正确值**（按“无箭头的完整价格框仍有选项”规则）：`options=['ANTIDOTE','PARLYZ HEAL','BURN HEAL','CANCEL']`，
  `option_details=['¥100','¥200','¥250','']`，四行单列，`cursor=''`、`cursor_cell=null`，`overlay=choice`。
- **证据**：`wListPointer`=0xCF7B（商品表 POKé BALL/ANTIDOTE/PARLYZ HEAL/BURN HEAL），`wListScrollOffset`=1，框完整（(2,4)┌ 至 (12,4)└，无数量框）。
  同类的 c-0492、c-0497（未滚动、无 CANCEL）真值给出了 4 个选项。差异来自“每一项都必须有价格”的识别条件把无价格的 `CANCEL` 当成残片。
- **影响**：低（仅开放脚本的场合，NONE 与 CHOICE 掩码相同），但两组同类帧口径不一。

### I. 0xFF 黑块被渲成 `9`，c-0467 场合错判（两者共同错误）

- **字段**：`screen`；c-0467 另有 `scene`。
- **帧**：c-0225、c-0226、c-0766（`transition`，整屏或边缘一片 `9999…`）；c-0467（`battle`，对角擦除）。
- **证据**：进入战斗的擦除动画用图块 0xFF 画黑块（截图 c-0225、c-0766、c-0467 均为黑色），并非数字 9。
  c-0467 `wIsInBattle`=1 但屏上没有任何战斗 HUD/文字，只有擦除，与 c-0225/c-0226（`wIsInBattle`=0，标 transition）是同一种画面。
- **正确值**：这些帧的 `screen` 应不含 `9`（按非文字图块处理或判空）；c-0467 的 `scene` 应为 `transition`。
- **影响**：低–中。生产中每场战斗开始都会经过此类帧，整屏 `9` 可能误导模型。

### J. 标题画面被判过场（两者共同错误，生产范围外）

- **字段**：`scene`、`screen`。
- **帧**：c-0009、c-0010、c-0011。
- **证据**：图块 0x80–0xDF 在第 1–7 行按顺序排列是 Logo 图形（截图 c-0010/c-0011：Pokémon Logo、Red Version、主角与御三家），
  真值 `screen` 却渲成 `ABCDEFGHIJKLMNOP / QRSTUVWXYZ():;[] / abcdef…`。标题画面不会自行推进，需要按 START/A，判 `transition`（等待）会一直等下去。
- **正确值**：`scene=title`（或另立“标题待机”），`screen` 不应出现伪字母。另 c-0003–c-0005（版权页）`screen` 中的 `ID`、`└`、`─` 也是 Logo 图块误渲。
- **影响**：低（SPEC 写明标题不进入生产范围）。

### K. 场合边界待裁决

| 帧 | 当前 | 观察 | 建议 |
|---|---|---|---|
| c-0247、c-0248、c-0249 | `battle` | 战斗中从换人子菜单进入的能力页（`STATUS/OK`、`TYPE1/`、`EXP POINTS`） | 可考虑 `pokemon_info`；需裁决 |
| c-0659 | `battle` | 捕获后弹出的图鉴条目页（`TINY BIRD`、`HT`、`WT`） | 同上 |
| c-0440 | `transition` | 野外背包框已画、列表尚空（截图为“That's too important to toss!”之后的重绘） | 与 c-0241（战斗中空背包框，用户裁决为 `battle_menu`）口径不一；可考虑 `bag`、`at_start=false` |
| c-0419 | `transition` | 开始菜单框已画、条目尚空 | 同类口径问题 |

影响均低（这些帧只需等待或按 A/B）。

### L. 已完整解出的队伍/图鉴列表 `covered=false`（契约问题，需裁决）

- **字段**：`screen_truth.covered`（不在基线内）。
- **帧（26）**：c-0243、c-0244、c-0246、c-0251、c-0423、c-0428–c-0431、c-0865–c-0867、c-0946、c-0948–c-0951、c-0954–c-0956、p-field_party_list、p-battle_use_on_which、p-battle_party_1、p-battle_party_2、takeover:faint_switch、takeover:party。
- **观察**：这些帧的选项、光标与 RAM 完全一致（队伍数 = `wPartyCount`(0xD163)），但真值把“非框选布局”一律记为未覆盖。
  `covered` 会转成 `menu_decode_complete=false`，在观测里提示“选单切分不全”，与事实不符。
- **建议**：明确 `covered` 对布局识别结果的含义；若表示“切分完整”，这些帧应为 `true`。

### M. 渲染细节（两者共同，契约渲染）

- 命名页名字槽（图块 0x76 = 空槽、0x77 = 当前位置标记）被当成战斗 HUD 框线，渲成 `┘──────`（30 帧，如 c-0037 第 3 行），
  模型可能读成框角；宝可梦昵称页同理 ` NICKNAME?┘─────────`。
- 图鉴/能力页的 `№`（0x74）后紧跟 `<DOT>`（0xF2），渲成 `No..001`（c-0149–c-0153、p-stats_page 等 6 帧）；战斗中同页渲成 `·.001`。
- 影响很低，记录备查。

### 附：契约层面的小问题（不计入错误）

- 队伍列表还没画出实心箭头时（c-0421、c-0424、c-0945、c-0947，其中两帧有空心 `▷`），因底部只有对话框、没有别的边框，按契约成为 `strict_dialog=true`、`overlay=dialog`（只给 `a`）。语义上这是菜单而非对话；因属仅开放脚本的场合，对动作无实际影响。
- 数量框残留而文字仍在打印（c-0443、c-0444、c-0581、p-pc_withdrew 等）时 `overlay=choice`，符合契约。

## 五、实际检查范围

**全量自动独立复算（1045 帧）**：`tiles`/`wTileMap` 一致性；`screen`、`dialog_text`、`quantity_box`、`strict_dialog`、`overlay`、
`has_cursor`、`cursor_cell`、`in_battle`、`covered_by_script`、`at_start` 是否为 null；场合与 `wIsInBattle` 的对应。

**按 RAM 菜单变量逐帧核对（169 帧有选项或光标）**：箭头位置、`cursor`、`cursor_cell`；其中 38 帧列表菜单逐项核对可见项与滚动；143 个选项附注逐项核对。

**业务视图（241 帧）**：八类视图全部字段（队伍、背包、金钱、商品与价格、战斗双方、训练师标志、在场标记、学招、PC 道具、箱、箱号、命名 target/typed）。

**地形（1032 帧）**：五字段全部；通行图逐格复算；精灵层另用隐藏标志、地图坐标两套模型对照；地图头 tileset 核对。

**人工逐组审阅**：按“真值签名”去重后的 580 组全部过了一遍：
`battle` 164 组（全部对话文本行；非严格对话的组全屏审阅）、`dialog` 155 组、`shop_items` 88 组（全部摘要 + 8 组全屏）、
`battle_menu` 36、`bag` 34、`naming` 30、`start_menu` 16、`transition`/`title` 12、`shop` 10、`pc` 10、`party` 9、`battle_switch` 8、
`pokemon_info` 6、`learn_move` 1、`walk` 1 组（282 帧，确认屏幕均无字无框）。
截图目视：c-0003、c-0009–c-0014、c-0037、c-0057、c-0088、c-0099、c-0109、c-0113、c-0115、c-0116、c-0155、c-0156、c-0198、c-0205、c-0218、
c-0225、c-0261、c-0267、c-0268、c-0272–c-0274、c-0350、c-0371、c-0390–c-0392、c-0413、c-0416、c-0419、c-0440、c-0467、c-0471、c-0659、c-0663、c-0707、c-0766。

## 六、未覆盖范围

样本里没有、因此本次无法验证真值与 decoder 的情形：

- 小写键盘、光标停在空格键或 `lower case` 行；
- 队伍 ≥3 只、带 PSN/BRN/PAR/SLP/FRZ 状态、等级 ≥100（无 `:L`）的队伍列表；教学技能机/进化石时显示 `ABLE/NOT ABLE` 的队伍列表；
- 非空的 PC 箱、取出宝可梦列表、换箱后的箱号；学招时“选择要忘记的招式”列表；
- 招式框第 4 招、多于 1 个重复名字的普通菜单、双位数以上的背包数量列表（只见到数量框 `×12`）；
- 野外有台阶以外的特殊碰撞（水面、柜台隔着对话）、可推动的巨石、`0x40–0x48` 等特殊静止精灵；
- 其他城市的商店（`MART_TILESET` 只核过常青市）、非英文红版。

另：本次未重跑 decoder、未运行模拟器验证操作行为；A、C、E 的修正应在模拟器里复测一次再定稿。

## 附录

**附录 1：A 类 177 帧**：c-0115–c-0268（连续 154 帧）、c-0272、c-0273、c-0392–c-0408、c-0413–c-0416。

**附录 2：A 类四邻改变的 113 帧**：c-0116、c-0156–c-0216、c-0218–c-0267、c-0272。
按场合：dialog 53、walk 18、battle 17、battle_menu 8、transition 6、naming 6、battle_switch 5。

**附录 3：命名帧 30**：c-0037–c-0044、c-0057–c-0065、c-0198–c-0203、c-0663–c-0668、takeover:naming。

**复现脚本**：本次的独立参考实现与中间产物只放在会话临时目录，未写入仓库；如需留档可再整理成 `scripts/` 下的只读核对脚本。
