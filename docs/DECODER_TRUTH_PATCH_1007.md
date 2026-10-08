# decoder 真值补丁清单（2026-10-07，待审）

> 依据：`docs/DECODER_TRUTH_AUDIT_1007.md` 及用户对其建议的认可。
> 机器可读清单：`eval_results/labeling_1007/truth_patch_1007.json`（每条：`sample_id` / `group` / `field` / `before` / `after` / `issue`）。
> **本文件只列改动，`truth.jsonl` 尚未修改。** 全部取自现有冻结 WRAM 与 ROM，没有重新采集。

## 一、总量

710 条字段改动，涉及 490 帧；另有 1 帧（c-0109）的地形改记为无法判定。

| 编号 | 规则 | 改动条数 | 帧数 | 进 13 字段基线 |
|---|---|---:|---:|---|
| A | 隐藏的 missable 物件（0xD5CE 列表 + 0xD5A6 位图）不进地形 | 283 | 172 | 否 |
| A+D | 同 A，另 `wGrassTile`=0xFF 时不产生 `G` | 6 | 3 | 否 |
| B | 精灵格位改用地图坐标（0xC2x4/0xC2x5 − 4）：换图首帧屏幕坐标未刷新 | 9 | 9 | 否 |
| B2 | 同 B：屏外/未绘制精灵的屏幕坐标是陈旧值；走动中的 NPC 记为目标格 | 229 | 225 | 否 |
| C | 换图中间帧：`scene=transition`，地形不适用 | 26 | 13 | scene |
| E | 昵称页 `target=NICKNAME?` | 12 | 12 | 否 |
| F | 战斗招式空位 `-` 不是选项 | 48 | 16 | options / option_grid / option_details |
| H | 无箭头、滚到底的完整商品框给出选项 | 8 | 2 | options / option_grid / option_details / overlay |
| I | 0xFF 黑块不渲成 `9`；c-0467 改 `transition` | 5 | 4 | screen / scene |
| J | 标题、版权页的 Logo 图块不渲成字母；标题待机页 `scene=title` | 9 | 6 | screen / scene |
| K | 战斗中的能力页、图鉴页改 `pokemon_info`；空列表框按所属菜单 | 9 | 6 | scene（c-0440 另含接管组） |
| L | 已识别布局（队伍、图鉴列表）`covered=true` | 26 | 26 | 否 |
| M | 命名名字槽 0x76/0x77 渲成 `_`；`№` 后接 `.` 时渲成 `No.` | 40 | 40 | screen |

G（命名键盘空格键）按建议维持 8 项，不改真值，只在 SPEC 里注明“空格键可选但不提供”。

## 二、地形精灵层：为什么一次改了 400 多帧

审计时只确认了 A、B。把精灵定位换成地图坐标后，又暴露出更大的一类（B2）：
**屏幕外或未绘制的精灵（图像号 0xC1x2 = 0xFF）不再刷新屏幕坐标**，原逻辑按陈旧像素坐标把它们画进当前屏。
典型是多个精灵挤在同一个像素点上，如 c-0730 七个精灵都在 (0,64)、c-0602 六个在 (32,4)。

抽查截图（RAM 与截图同刻的帧）：

| 帧 | 当前真值 | 补丁后 | 截图 |
|---|---|---|---|
| c-0730 | 第 4 行 `N..N@.....` | `...N@.....` | (0,4) 是树，无人 |
| c-0602 | 第 0 行 `#.N.......`、第 3 行 `#....#N##.` | `#.........`、`#....####.` | 两处均无人 |
| c-0313 | 第 1 行 `..#..#..N.` | `..#..#....` | 无人 |
| c-0322 / c-0373 / c-0453 | 左侧或下方有 `N` | 无 | 栅栏、草丛，无人 |
| c-0355 | 第 0 行 `###..#####` | `###.N#####` | 柜台上方确有店员——原逻辑因屏幕 y 坐标回绕（252）漏掉了 |
| c-0691 | 四邻 `北 .` | `北 N` | 女孩确在主角正北 |
| c-0099 | 大木在列 2 | 列 3 | 列 3 |
| c-0088 | 妈妈在第 5 行 | 第 6 行 | 第 6 行（镜头滚动中，屏幕坐标偏移） |

走动中的 NPC（如 c-0280、c-0479、c-0489）屏幕上介于两格之间，补丁记为**目标格**：
游戏在起步时就把地图坐标更新为目标格，碰撞也以它为准。如需改记“出发格”，告诉我再重算。

c-0109 是开场大木带路的脚本移动帧：屏幕坐标、地图坐标和截图三者都对不上，改为写进 `unresolved_fields`，地形组不计分。

四邻改变共 119 帧：A 类 114、B2 类 5（c-0109 已转为不计分；c-0112、c-0479、c-0680、c-0691 已与截图核对）。

## 三、其余各项的代表改动

| 编号 | 帧 | 字段 | 修改前 | 修改后 |
|---|---|---|---|---|
| A | c-0272 | neighbors | `北 . 南 . 西 . 东 N` | `北 . 南 . 西 . 东 .` |
| A | c-0261 | walk_map 第 1、5 行 | `.....III.#`、`###.N#####` | `.....#I#.#`、`###..#####` |
| A+D | c-0257 | walk_map 第 5 行 | `###GN#####` | `##########` |
| C | c-0273 | scene / terrain | `walk` / `地图37 x=5 y=5 …` | `transition` / 不适用 |
| E | c-0198 | view.target | `BULBASAUR ·` | `NICKNAME?` |
| F | c-0239 | options | `TACKLE, GROWL, -, -` | `TACKLE, GROWL` |
| H | c-0493 | options / details / overlay | `[]` / `[]` / `none` | `ANTIDOTE, PARLYZ HEAL, BURN HEAL, CANCEL` / `¥100, ¥200, ¥250, ""` / `choice` |
| I | c-0766 | screen | 18 行 `9999…` | `""` |
| I | c-0467 | scene | `battle` | `transition` |
| J | c-0010 | scene / screen | `transition` / `ABCDEF…` | `title` / `""` |
| K | c-0247 | scene | `battle` | `pokemon_info` |
| K | c-0440 | scene / covered_by_script / at_start / view | `transition` / false / null / null | `bag` / true / false / 背包 + 队伍（RAM 读出） |
| L | c-0243 | covered | false | true |
| M | c-0037 | screen 第 3 行 | `          ┘──────` | `          _______` |
| M | c-0149 | screen | `No..001` | `No.001` |

完整逐帧列表在 JSON 里，按 `issue` 过滤即可。

## 四、审完之后的步骤

1. 按本清单改 `truth.jsonl`（保留修改前快照），重跑 `python -m evals.dataset.frames.build.coverage` 和结构检查。
2. 跑 decoder 基线，确认失败的正好是上面这些帧和字段。
3. 按 A/B/B2/D → C → E → F → H → I/J → K → L → M 的顺序修 decoder，每项一条 CHANGELOG、一个 commit。
4. 同步 `docs/spec/world/SPEC.md`、`docs/spec/evals/SPEC.md`、`DECODER_RELABEL_1007.md` 中被改动的规则，包括 F 和 G 的新口径。
