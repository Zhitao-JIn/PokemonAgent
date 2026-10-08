# P0 探测结果（intent 第八节）

> 日期：2026-09-26 ｜ 做法：knowledge 存档 + 从开机新游戏按键进各界面，逐帧取内存变量、屏幕缓冲与截图；
> 脚本在设备 `~/probe/`（`discrim.py` / `scr.py` / `buyflow.py` / `nameflow.py` / `catch.py` / `classify.py`），不在仓库。
> 地址来自 pret/pokered 符号表，**本文只写实测过的**。

## 一、界面判别

**结论：以屏幕缓冲的固定特征为主，内存变量只作旁证。** 列表类变量（`wListMenuID` 0xCF94、`wListPointer` 0xCF8B、
`wPrintItemPrices` 0xCF93）退出界面后不清零，走路帧上仍是上一次的值；`wNamingScreenType` 0xD07D 与
`wPartyMenuTypeOrMessageID` 共用地址，也会残留。缓冲特征在 observation_check 406 帧（只有截图）上也能用。

| 界面 | 缓冲特征 | 内存旁证（实测） |
|---|---|---|
| 起名 | 键盘行 `A B C D E F G H I`（或小写） | 战斗中给宝可梦起昵称时 `wIsInBattle` 仍为 1——**先判起名再判战斗** |
| 商店购买列表 | `MONEY` 框 + `▶` 列表 + 附注全是 `¥` | `wListPointer`=0xCF7B（商店货单）、`wPrintItemPrices`=1 |
| 商店卖出列表 | 对话以 `like to sell?` 结尾 + `▶` 列表 | `wListPointer`=0xD31D（背包） |
| PC 取出 / 存入 / 丢弃 | 对话以 `withdraw?` / `deposit?` / `toss away?` 结尾 + `▶` 列表 | 取出、丢弃 0xD53A（PC 箱子）；存入 0xD31D（背包） |
| 数量框 | `×` 紧跟两位数字、屏幕上没有 `▶`、对话不是确认句（`… That will be …`） | `wItemQuantity` 0xCF96 / `wMaxItemQuantity` 0xCF97 |
| 队伍列表 | `▶` 在第 0 列、无框，有 `:L` 与 `HP:` | `wListMenuID`=2 |

**规则原型在 451 帧上的分布**：走路 179、纯对话 169、选单 59、其余 20、数量框 11、购买列表 5、队伍列表 4、起名 2、
切不出的选单 1（图鉴）、PC 取出 1。"其余"逐帧看过：空对话框（过渡帧）8、战斗 HUD 上的空对话框 3、信息页（能力页、
训练家卡片、图鉴条目）5、光标闪烁那一帧的招式列表 1、城镇地图地名 1、`▷` 残留的商店主菜单 1、战斗过场 1——
都不属于要接管的界面。已知误判 1 帧：`p-shop_confirm`（确认台词 + 残留数量框）判成了数量框，按上表"对话不是确认句"修。
卖出、PC 存入 / 丢弃、对手 / 宝可梦起名在 451 帧里没有样本，需补进数据集（第四节）。

截图还原的一处修正：走路帧里地图图块偶尔与 HUD 图块同形（`]`、`┘`），被还原成 HUD 字符、让整屏"有字"。
改为：一个字母 / 数字都没有的帧，HUD 图块一律当非文字（`glyphs.py`）。修后走路 16 → 179。

## 二、商店

| 项 | 来源 | 实测 |
|---|---|---|
| 完整货单 | `wItemList` 0xCF7B：数量 + 物品 ID + 0xFF | ✅ 与屏幕 4 项一致 |
| 名字 | ROM `ItemNames` 0x472B，按 ID | ✅ |
| 买价 | ROM `ItemPrices` 0x4608，3 字节 BCD | ✅ 200/100/200/250，POTION 300 |
| 卖价 | 买价的一半 | ✅ POTION 数量框显示 ¥150 |
| 金钱 | `wPlayerMoney` 0xD347，3 字节 BCD | ✅ |
| 背包 / PC 箱子 | 0xD31D + 成对（ID, 数量）/ 0xD53A + 成对，0xFF 结尾 | ✅ |
| 光标 = 第几项 | `wCurrentMenuItem` 0xCC26 + `wListScrollOffset` 0xCC36 | ✅ 背包翻页 cur=2 scroll=1 → 第 3 项 ANTIDOTE；翻到底 scroll=6 → CANCEL |

**购买全流程（ANTIDOTE ×3，实测）**：列表 cur=0 → 下 → cur=1 → a → 数量框出现（`wItemQuantity`=1，上限 99）→ 上×2 → 3 →
a → 确认台词两页（`ANTIDOTE? That will be` / `That will be ¥300. OK?`）→ YES/NO（光标默认 YES）→ a → 金钱 3000→2700、
背包多出 `0x0B ×3` → `Here you are! Thank you!`。
- 上限 99 与钱无关：钱不够是在确认之后才说。所以钱够不够在解析 `buy` 时就算（单价 × 数量 ≤ 金钱）。
- 台词逐字打出、按键节奏不固定：执行器不能按固定次数按，要"按一下 → 读缓冲 / 内存 → 到了目标状态再下一步"。
- 重要道具（TOWN MAP）存入 PC 时**不弹数量框**，直接存（实测）。

## 三、起名

| 项 | 来源 | 实测 |
|---|---|---|
| 给谁起名 | 屏幕标题：`YOUR NAME?` / `RIVAL's NAME?` / `NICKNAME?`（昵称界面上方还显示是哪只，如 `PIDGEY`） | ✅ 三种都进过（开机新游戏走到主角、对手；knowledge_catch_throw_ball 抓到 PIDGEY 选 YES） |
| 已输入的名字 | `wStringBuffer` 0xCF4B | ✅ |
| 已输入长度 | `wNamingScreenNameLength` 0xCEE9 | ✅ 每输入一字 +1 |
| 键盘光标 | `wMenuCursorLocation` 0xCC30（光标所在的屏幕格；字母在它右边一格） | ✅ |
| 提交 | 输完按 START，名字即提交 | ✅ 输入 A、S、H 后 START：`wPlayerName` 0xD158 = `ASH`，台词 `Right! So your name is ASH!` |

键盘默认大写；名字只允许大写字母时执行器不必切大小写。

## 四、要补进读屏数据集的帧

卖出列表 / 卖出数量框、PC 存入 / 丢弃列表与数量框、对手起名、宝可梦昵称起名（存档已存在设备 `~/probe/out/`：
`at_rival_keyboard.state`、`at_nickname_prompt.state`、`at_nickname_keyboard.state`，写 spec 时拷进仓库）。

## 五、按 B 回初态（09-26 实测）

探测脚本：先走到宏的某个中途步骤，再连按 B（每次等 60 帧），逐次记屏幕、场合、金钱、背包、PC。
存档：`knowledge_shop_confirm_purchase` / `knowledge_shop_open_buy_menu` / `knowledge_pc_save` /
`knowledge_movement_obstacle`（背包注入 8 样）/ 探测时存的对手、昵称键盘。

| 宏 | 起点 | 按 B 的落点（依次） |
|---|---|---|
| buy | 数量框（调没调过数量都一样） | 列表 ▶ → 关列表"还要别的吗" → 上层菜单 ▶BUY → "Thank you!" → 出店 |
| buy | YES/NO | ▶YES 画完 → 列表 ▶ → 同上 |
| buy | 已付款的 "Here you are! Thank you!"（钱已扣、道具已入包） | 字打完 → 列表 ▶ → 同上 |
| sell | 数量框 / YES/NO | 列表 ▶ → 同上 |
| pc_withdraw | 数量框 / 已取出提示 "Withdrew POTION." | 列表 ▶（PC 取空时 ▶ 在 CANCEL）→ PC 菜单 ▶WITHDRAW ITEM → 选 PC 菜单 → 走路 |
| 背包 toss | 数量框 / "Is it OK to toss" YES/NO | 背包列表 ▶ → 开始菜单 ▶ITEM → 走路 |
| naming | 已输入 N 个字（对手、昵称都测了） | 每按一次删一个字；删空后再按 B **原地不动**，不会退出键盘 |

补测（初态按"主菜单 + 实心 `▶` + 无空心 `▷`"定）：

| 宏 | 起点 | 按 B 的落点（依次） |
|---|---|---|
| 战斗 | 招式列表 / 战斗背包 | 行动菜单（初态）；再按 B 原地不动，退不出战斗 |
| 战斗 | 背包→选对象的队伍列表 | 战斗背包 → 行动菜单 |
| 战斗 | 换人列表的 SWITCH 子菜单 | 换人列表 → 行动菜单 |
| 野外队伍 | STATS 子菜单 / 能力页 | 队伍列表（初态）→ 开始菜单 → 走路 |
| 背包 | 选对象的队伍列表 | 背包列表（初态）→ 开始菜单 → 走路 |
| PC | 比尔 PC 子菜单 / 道具取出数量框 | …→ 选哪台 PC（初态）→ 走路 |

结论：
1. 所有中途步骤连按 B 都会经过初态：商店 2–4 次，PC 2–4 次；**没有跳过初态直接退出的情况**。
2. 已到初态再按 B 会退出场合（商店 "Thank you!" 后出店；PC 回到选哪台 PC），所以**每按一次 B 之前先判一次是否已在初态**。
3. B 不会撤销已经发生的买卖 / 取出（钱、背包、PC 都保持变更后的值）：回初态后要重读观测，不能沿用宏开始前的。
4. 起名按 B 不改大小写与键盘光标：`wAlphabetCase`（0xCEEB）按 SELECT 切换（实测 0→1），`enter_name` 打字前自己切回大写。
5. 商店与 PC 道具各合成一个仅开放脚本的场合（`shop` / `pc_items`）：列表开着时上层菜单必留空心 `▷`，列表本身不可能是初态。
6. 未测：PC 存入 / 丢弃（按与取出同一版面推断，待补测）。

## 六、初态时宏要的参数在不在内存里（09-26 实测；地址取自 pokered.sym）

| 场合 | 参数 | 地址 | 实测 |
|---|---|---|---|
| `shop_items` | 商品表 | `wItemList` 0xCF7B（个数 + id） | 先清零再和店员说话：`▶BUY` 菜单一出来表就写好了，不用等进 BUY |
| `shop_items` | 在商店里（常规 `shop`） | `wCurMapTileset` 0xD367 = 2（MART） | 常青市商店；其它商店未核 |
| `battle_menu` | 出场宝可梦招式 / PP | `wBattleMonMoves` 0xD01C / `wBattleMonPP` 0xD02D（低 6 位） | 与 FIGHT 列表一致 |
| `party` / `battle_menu` | 队伍每只的招式 / PP | `wPartyMon1Moves` 0xD173 / `wPartyMon1PP` 0xD188，每只 +44 | 与能力页第二页一致 |
| `pc` | 当前箱的宝可梦 | `wBoxCount` 0xDA80、`wBoxSpecies` 0xDA81、`wBoxMonNicks` 0xDE06 | 存入一只后个数、种类、昵称都更新；只有当前箱（`wCurrentBoxNum` 0xD5A0） |
| `learn_move` | 提示文案 | ROM 文本 | `Delete an older / move to make room / for XX?`、`Which move should / be forgotten?`、`Abandon learning` 都在；屏上未见过 |

