# 实际帧的 scene × overlay 决策显示核对（2026-10-07）

逐一重读统一 v2 的1045份冻结 WRAM，不启动模拟器、不调用真实模型。1043帧有场合真值（新增仍待审），2帧场合待裁决。以独立场合标注分组，overlay 记录当前实际解码值；有独立 overlay 真值时同步对照，缺真值的组合只算观察到，不能算已审核正确。

16个场合 × 3种 overlay 共48种候选组合，当前帧集中观察到26种。另22种没有实际帧，不能伪造例子，也不由缺样推出不可能。旧 p-shop_confirm、p-pc_withdrew 的 overlay 真值为 dialog，但实际屏幕仍有数量框；本报告按当前 choice 归组，保留旧标注分歧，不改真值。

“够”表示给定明确审核目标后，显示中有候选动作及参数的依据，且候选通过当前动作空间/参数形状核对；不证明模型会选择它，不证明按键或脚本执行成功。审核目标是本次人为指定的检查条件，不是采集帧自带目标。

## 全组合矩阵

| scene | none | dialog | choice |
|---|---|---|---|
| walk | 282帧；c-0637 | 未采到 | 未采到 |
| dialog | 未采到 | 206帧；c-0394 | 2帧；c-0055 |
| battle | 11帧；c-0926 | 201帧；c-0933 | 1帧；c-0662 |
| shop | 12帧；c-0596 | 18帧；c-0356 | 未采到 |
| pokemon_info | 1帧；p-stats_page | 5帧；c-0153 | 未采到 |
| start_menu | 8帧；p-trainer_card | 未采到 | 20帧；p-start_menu |
| title | 未采到 | 未采到 | 1帧；c-0013 |
| transition | 34帧；c-0767 | 未采到 | 未采到 |
| naming | 未采到 | 未采到 | 30帧；c-0665 |
| shop_items | 38帧；c-0515 | 未采到 | 60帧；p-shop_menu_sell |
| pc | 未采到 | 未采到 | 11帧；p-pc_top |
| bag | 16帧；c-0986 | 未采到 | 24帧；c-0437 |
| battle_menu | 6帧；c-0245 | 未采到 | 42帧；c-0242 |
| faint_switch | 未采到 | 未采到 | 2帧；takeover:faint_switch |
| party | 未采到 | 4帧；c-0421 | 7帧；p-field_party_list |
| learn_move | 未采到 | 未采到 | 1帧；takeover:learn_move |

## 逐组合实际显示与下一步核对

### bag × choice — c-0437

实际组合共24帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=bag，场合真值=bag；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
背包：POTION ×1、TOWN MAP ×1
队伍：BB?! L6 HP 14/22
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：bag_use、bag_toss、bag_close。

审核目标：给 BB?! 用一瓶药。

候选下一步：`{"action": "bag_use", "args": {"item": "POTION", "pokemon": "BB?!"}}`

判断：**够**。POTION ×1，BB?! HP14/22，存在治疗空间；当前光标在 TOWN MAP 不影响目标脚本选择。

### bag × none — c-0986

实际组合共16帧；其中3帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=bag，场合真值=bag；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
背包：POTION ×1、TOWN MAP ×1、POKé BALL ×3、ANTIDOTE ×1、PARLYZ HEAL ×1、BURN HEAL ×1
队伍：BB?! L8 HP 16/26；PP!? L6 HP 9/20
selected_map_location: ROUTE 15
where: 全局坐标 地图51 x=26 y=33
```

可调用按键：无。
可调用脚本：bag_use、bag_toss、bag_close。

审核目标：看清城镇地图文字后退出。

候选下一步：`{"action": "bag_close"}`

判断：**有条件**。本帧选中地点是 ROUTE 15；补回屏幕后才能读到，不能把它当主角当前地点。bag_close 可调用。若目标是移动城镇地图光标，现有动作空间没有相应操作，字段再全也不够。

### battle × choice — c-0662

实际组合共1帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=battle，场合真值=battle；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: battle
- covered_by_script: false
- overlay: choice
- screen:               ┌────┐
              │▶YES│
              │    │
              │ NO │
              └────┘
┌──────────────────┐
│                  │
│give a nickname   │
│                  │
│to PIDGEY?        │
└──────────────────┘
- my_name: BB?!
- my_level: 6
- my_hp: 12/22
- foe_name: PIDGEY
- foe_level: 5
- foe_hp: 7/19
- foe_status: ok
- my_status: ok
- menu_decode_complete: true
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：不给刚捕获的 PIDGEY 起昵称。

候选下一步：`{"action": "down"}`

判断：**够**。问题 give a nickname to PIDGEY?，光标在 YES；下一步 down 移到 NO，之后需新观测再确认。此时 RAM 的对手 HP 是残留战斗信息，不代表仍需攻击。

### battle × dialog — c-0933

实际组合共201帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=battle，场合真值=battle；overlay 解码=dialog，独立真值=dialog；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: battle
- covered_by_script: false
- overlay: dialog
- dialog_text: RED got ¥60 for winning!
```

可调用按键：a。
可调用脚本：无。

审核目标：继续战斗结算。

候选下一步：`{"action": "a"}`

判断：**够**。RED got ¥60 for winning! 明确是获胜结算，a 推进；战斗标志已清所以没有双方状态字段。

### battle × none — c-0926

实际组合共11帧；其中1帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=battle，场合真值=battle；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: battle
- covered_by_script: false
- overlay: none
- screen:          ┌─────────┐
         │ ATTACK  │
         │      10 │
 ······· │ DEFENSE │
 ······· │       9 │
 ······· │ SPEED   │
 ······· │      13 │
 ······· │ SPECIAL │
 ······· │      10 │
 ······· └─────────┘
┌──────────────────┐
│                  │
│PP!? grew         │
│                  │
│to level 6!       │
└──────────────────┘
- my_name: PP!?
- my_level: 6
- my_hp: 9/20
- foe_name: CATERPIE
- foe_level: 6
- foe_hp: 0/22
- foe_status: ok
- my_status: ok
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：继续升级结算。

候选下一步：`{"action": "a"}`

判断：**有条件**。屏幕写 PP!? grew to level 6! 并显示能力框；a 是合法候选，但静态快照不能证明动画已稳定或这一键一定推进。

### battle_menu × choice — c-0242

实际组合共42帧；其中3帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=battle_menu，场合真值=battle_menu；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
对战：训练家对战
我方：BB?! L5 HP 20/20（在场）
招式：TACKLE（PP 35）、GROWL（PP 40）
对手：CHARMANDER L5 HP 19/19
队伍：BB?! L5 HP 20/20（在场）
背包：（空）
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：battle_fight、battle_switch、battle_use_item、battle_run。

审核目标：用 TACKLE 攻击。

候选下一步：`{"action": "battle_fight", "args": {"move": "TACKLE"}}`

判断：**够**。招式 TACKLE PP35 可指定，脚本在当前动作空间。训练家对战不能逃跑。仅保证能给出有依据的候选，不足以比较最优伤害；缺属性、威力等信息。

### battle_menu × none — c-0245

实际组合共6帧；其中6帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=battle_menu，场合真值=battle_menu；overlay 解码=none，独立真值=未标；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
对战：训练家对战
我方：BB?! L5 HP 20/20（在场）
招式：TACKLE（PP 35）、GROWL（PP 40）
对手：CHARMANDER L5 HP 19/19
队伍：BB?! L5 HP 20/20（在场）
背包：（空）
```

可调用按键：无。
可调用脚本：battle_fight、battle_switch、battle_use_item、battle_run。

审核目标：用 TACKLE 攻击。

候选下一步：`{"action": "battle_fight", "args": {"move": "TACKLE"}}`

判断：**有条件**。业务视图与主菜单相同，at_start=false 留给脚本恢复；能选择脚本，不代表重画中的界面可立刻成功恢复。另有5帧本场合被误判成 battle，显示字段无法修复错误路由。

### dialog × choice — c-0055

实际组合共2帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=dialog，场合真值=dialog；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: dialog
- covered_by_script: false
- overlay: choice
- where: 全局坐标 地图38 x=3 y=6
- screen: ┌──NAME───┐
│         │
│▶NEW NAME│
│         │
│ BLUE    │········
│         │ ·······
│ GARY    │ ·······
│         │ ·······
│ JOHN    │ ·······
│         │ ·······
│         │ ·····
└─────────┘
┌──────────────────┐
│                  │
│...Erm, what is   │
│                  │
│his name again?   │
└──────────────────┘
- menu_decode_complete: true
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：advance_dialog、wait_until_scene。

审核目标：给对手自定义名字。

候选下一步：`{"action": "a"}`

判断：**够**。屏幕问题问对手叫什么，实心光标指向 NEW NAME；a 确认后才进入起名键盘。

### dialog × dialog — c-0394

实际组合共206帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=dialog，场合真值=dialog；overlay 解码=dialog，独立真值=dialog；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: dialog
- covered_by_script: false
- overlay: dialog
- where: 全局坐标 地图40 x=5 y=3
- dialog_text: OAK: Oh, RED!
```

可调用按键：a。
可调用脚本：advance_dialog、wait_until_scene。

审核目标：继续博士对话。

候选下一步：`{"action": "a"}`

判断：**够**。当前文字 OAK: Oh, RED!，动作空间只开放 a；已补回地图40与坐标。不能仅由这一句证明整个任务完成。

### faint_switch × choice — takeover:faint_switch

实际组合共2帧；其中1帧没有独立 overlay 真值。代表帧 source=takeover_snapshot；scene 解码=faint_switch，场合真值=faint_switch；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
队伍：BULBASAUR L7 HP 0/25（在场、倒下）；PIDGEY L3 HP 15/15
- menu_decode_complete: false
- observation_notes: 选单切分不完整，接管参数以业务视图为准；缺选项不表示没有选单
```

可调用按键：无。
可调用脚本：faint_send_out。

审核目标：换上还能战斗的队员。

候选下一步：`{"action": "faint_send_out", "args": {"pokemon": "PIDGEY"}}`

判断：**够**。BULBASAUR HP0/25 已倒下，PIDGEY HP15/15；能据此选 PIDGEY。

### learn_move × choice — takeover:learn_move

实际组合共1帧；其中0帧没有独立 overlay 真值。代表帧 source=takeover_snapshot；scene 解码=learn_move，场合真值=learn_move；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
BB?! 想学 VINE WHIP
现有的招：TACKLE（PP 28）、GROWL（PP 40）、LEECH SEED（PP 8）、GUST（PP 35）
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：learn_forget、learn_skip。

审核目标：忘掉 GROWL，学习 VINE WHIP。

候选下一步：`{"action": "learn_forget", "args": {"move": "GROWL"}}`

判断：**够**。新招 VINE WHIP、现有 GROWL PP40 都在视图；目标明确指定替换，不依赖隐藏光标。若要求最优配招，当前字段不足。

### naming × choice — c-0665

实际组合共30帧；其中3帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=naming，场合真值=naming；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
起名：PIDGEY ·
已输入：PP
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：naming_enter_name。

审核目标：将捕获的宝可梦命名为 PIDGEY。

候选下一步：`{"action": "naming_enter_name", "args": {"name": "PIDGEY"}}`

判断：**有条件**。当前目标标题 PIDGEY ·，已输入 PP；可以按目标给出全大写合法名称。用户想起什么名字必须来自目标，不能从当前字段自行推断；标题含图像占位符是解码限制。

### party × choice — p-field_party_list

实际组合共7帧；其中1帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=party，场合真值=party；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
队伍：
1. BULBASAUR L5 HP 20/20；招式：TACKLE、GROWL
- menu_decode_complete: false
- observation_notes: 选单切分不完整，接管参数以业务视图为准；缺选项不表示没有选单
```

可调用按键：无。
可调用脚本：party_switch、party_field_move、party_stats、party_close。

审核目标：查看 BULBASAUR 能力。

候选下一步：`{"action": "party_stats", "args": {"pokemon": "BULBASAUR"}}`

判断：**够**。队伍只有 BULBASAUR，名称可直接作为参数；party_stats 已开放。

### party × dialog — c-0421

实际组合共4帧；其中4帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=party，场合真值=party；overlay 解码=dialog，独立真值=未标；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
队伍：
1. BB?! L6 HP 14/22；招式：TACKLE、GROWL
```

可调用按键：无。
可调用脚本：party_switch、party_field_move、party_stats、party_close。

审核目标：查看 BB?! 能力。

候选下一步：`{"action": "party_stats", "args": {"pokemon": "BB?!"}}`

判断：**有条件**。队伍 BB?! 可指定，业务视图仍在；屏幕仅有空心光标和 Choose a POKéMON，初态为false，脚本需要先稳定与恢复。overlay 尚无独立真值。

### pc × choice — p-pc_top

实际组合共11帧；其中1帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=pc，场合真值=pc；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
PC 道具：POTION ×1
背包：TOWN MAP ×1、POKé BALL ×4
当前箱 BOX 1：（空）
队伍：BULBASAUR L10 HP 32/32；PIDGEY L5 HP 19/19
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：pc_withdraw_item、pc_deposit_item、pc_toss_item、pc_withdraw_pokemon、pc_deposit_pokemon、pc_change_box、pc_log_off。

审核目标：从 PC 取一瓶药。

候选下一步：`{"action": "pc_withdraw_item", "args": {"item": "POTION", "quantity": 1}}`

判断：**够**。PC 中 POTION ×1，背包没有 POTION，脚本与参数签名均存在；不用模型操作 PC 层级菜单。

### pokemon_info × dialog — c-0153

实际组合共5帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=pokemon_info，场合真值=pokemon_info；overlay 解码=dialog，独立真值=dialog；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: pokemon_info
- covered_by_script: false
- overlay: dialog
- screen: ····················
········           ·
········ BULBASAUR ·
········           ·
········ SEED      ·
········           ·
········ HT  2·04· ·
········           ·
· No..001  WT  15.0lb·
····················
·                  ·
·The plant sprouts ·
·                  ·
·and grows with    ·
·                  ·
·this POKéMON.     ·
·                  ·
·└└└└└└└└└└└└└└└└└└·
```

可调用按键：a。
可调用脚本：无。

审核目标：读完图鉴说明继续。

候选下一步：`{"action": "a"}`

判断：**有条件**。屏幕保留 BULBASAUR、SEED 和完整说明，a 合法。若要求按 b 返回，当前 dialog 掩码只有 a，会挡住 b，需要单独核对能力掩码。

### pokemon_info × none — p-stats_page

实际组合共1帧；其中0帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=pokemon_info，场合真值=pokemon_info；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: pokemon_info
- covered_by_script: false
- overlay: none
- screen:  ·······
 ······· BULBASAUR │
 ·······      :L5   │
 ·······   HP:[██████]
 ·······     20/ 20│
 ·······           │
 ······· STATUS/OK │
 No..001  └──────────┘
┌────────┐
│ATTACK  │TYPE1/   │
│      10│ GRASS   │
│DEFENSE │TYPE2/   │
│      10│ POISON  │
│SPEED   │ID·/      │
│      10│  51883  │
│SPECIAL │OT/      │
│      12│  RED    │
└────────┘  └──────┘
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：退出能力页。

候选下一步：`{"action": "b"}`

判断：**够**。完整页显示 BULBASAUR L5 HP20/20 等信息，b 已开放；页面文字没有被缩减丢掉。

### shop × dialog — c-0356

实际组合共18帧；其中0帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=shop，场合真值=shop；overlay 解码=dialog，独立真值=dialog；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: shop
- covered_by_script: false
- overlay: dialog
- where: 全局坐标 地图42 x=3 y=7
- dialog_text: Hey! You came
```

可调用按键：a。
可调用脚本：无。

审核目标：继续店员交谈。

候选下一步：`{"action": "a"}`

判断：**够**。实际半句 Hey! You came 按原样保留，不补全；地点地图42坐标 (3,7)，合法 a。

### shop × none — c-0596

实际组合共12帧；其中1帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=shop，场合真值=shop；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: shop
- covered_by_script: false
- overlay: none
- where: 全局坐标 地图42 x=3 y=6
- facing: south
- landmarks: 人 x=3 y=2; 人 x=0 y=4; 人 x=5 y=5; 门 x=3 y=7; 门 x=4 y=7
- walk_map: 这一屏 10 列 × 9 行；每行末尾括号里是该行首尾两格的全局 x
y=2  ###.N#####  (x=-1..8)
y=3  ###..#####  (x=-1..8)
y=4  #N#......#  (x=-1..8)
y=5  ###...N..#  (x=-1..8)
y=6  #...@....#  (x=-1..8)
y=7  ####DD####  (x=-1..8)
y=8  ##########  (x=-1..8)
y=9  ##########  (x=-1..8)
y=10 ##########  (x=-1..8)
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：朝商店出口移动一格。

候选下一步：`{"action": "down"}`

判断：**够**。已补回地图42、位置 (3,6)、朝向 south 和网格；下方 (3,7) 标为门 D，down 合法。退出是否完成仍看新帧。

### shop_items × choice — p-shop_menu_sell

实际组合共60帧；其中1帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=shop_items，场合真值=shop_items；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
商品：POKé BALL ¥200、ANTIDOTE ¥100、PARLYZ HEAL ¥200、BURN HEAL ¥250
金钱：¥3000
背包：POTION ×1
- menu_decode_complete: true
```

可调用按键：无。
可调用脚本：buy_item、sell_item、shop_quit。

审核目标：买一个精灵球。

候选下一步：`{"action": "buy_item", "args": {"item": "POKé BALL", "count": 1}}`

判断：**够**。商品 POKé BALL 单价200，金钱3000，背包 POTION ×1；buy_item 存在。当前光标在 SELL 不影响调用，恢复主菜单由脚本处理。

### shop_items × none — c-0515

实际组合共38帧；其中38帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=shop_items，场合真值=shop_items；overlay 解码=none，独立真值=未标；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- covered_by_script: true
商品：POKé BALL ¥200、ANTIDOTE ¥100、PARLYZ HEAL ¥200、BURN HEAL ¥250
金钱：¥1500
背包：POTION ×1、TOWN MAP ×1
```

可调用按键：无。
可调用脚本：buy_item、sell_item、shop_quit。

审核目标：买一个精灵球。

候选下一步：`{"action": "buy_item", "args": {"item": "POKé BALL", "count": 1}}`

判断：**有条件**。金钱1500且商品单价200，可以组装参数；空心光标和半句说明界面在中间阶段，必须由脚本先稳定和恢复。

### start_menu × choice — p-start_menu

实际组合共20帧；其中2帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=start_menu，场合真值=start_menu；overlay 解码=choice，独立真值=choice；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: start_menu
- covered_by_script: false
- overlay: choice
- screen: ··········┌────────┐
··········│        │
··········│▶POKéMON│
··········│        │
··········│ ITEM   │
··········│        │
··········│ RED    │
··········│        │
··········│ SAVE   │
··········│        │
··········│ OPTION │
··········│        │
··········│ EXIT   │
··········└────────┘
····················
····················
····················
····················
- menu_decode_complete: true
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：打开队伍。

候选下一步：`{"action": "a"}`

判断：**够**。实心光标在 POKéMON，a 确认即可；目标若是背包则应先 down。

### start_menu × none — p-trainer_card

实际组合共8帧；其中5帧没有独立 overlay 真值。代表帧 source=probe_0926；scene 解码=start_menu，场合真值=start_menu；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: start_menu
- covered_by_script: false
- overlay: none
- screen: ┌──────────────────┐
│              ····│
│ NAME/RED     ····│
│              ····│
│ MONEY/¥3000  ····│
│              ····│
│ TIME/  0·24  ····│
└┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘
      ─BADGES─
·┌────────────────┐·
·│··· ··· ··· ··· │·
·│ ··  ··  ··  ·· │·
·│ ··  ··  ··  ·· │·
·│··· ··· ··· ··└ │·
·│ ··  ··  ··  ·· │·
·│ ··  ··  ··  ·· │·
·└┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘┘·
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：退出训练家卡片。

候选下一步：`{"action": "b"}`

判断：**够**。屏幕有 NAME/RED、MONEY/¥3000、TIME/0·24，能识别卡片，b 合法。

### title × choice — c-0013

实际组合共1帧；其中1帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=title，场合真值=title；overlay 解码=choice，独立真值=未标；地图已加载=False。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: title
- covered_by_script: false
- overlay: choice
- screen: ┌─────────────┐
│             │
│▶NEW GAME    │
│             │
│ OPTION      │
└─────────────┘
- menu_decode_complete: true
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：无。

审核目标：开始新游戏。

候选下一步：`{"action": "a"}`

判断：**运行范围外**。用户保证生产不会遇到标题菜单；保留该帧作为历史解码样本，本次不补无地图入口。

### transition × none — c-0767

实际组合共34帧；其中2帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=transition，场合真值=transition；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: transition
- covered_by_script: false
- overlay: none
- observation_notes: 未解码出屏幕文字，不能据此判断界面已结束；当前分类为过场，单帧不能判断是否稳定；需新观测确认
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：wait_until_scene。

审核目标：等待进入预期战斗场合并重新观察（预期场合来自任务上下文）。

候选下一步：`{"action": "wait_until_scene", "args": {"scene": "battle", "timeout_s": 10}}`。

判断：**有条件**。transition 已开放 wait_until_scene；只推进帧不按键。目标场合必须由上下文指定，匹配或超时后都重新感知；匹配不保证稳定。本次只核对动作空间与 prompt，不证明执行成功。

### walk × none — c-0637

实际组合共282帧；其中1帧没有独立 overlay 真值。代表帧 source=capture_0926；scene 解码=walk，场合真值=walk；overlay 解码=none，独立真值=none；地图已加载=True。

模型当前帧显示（接管 scene 由 prompt 的场合说明提供）：

```text
- scene: walk
- covered_by_script: false
- overlay: none
- where: 全局坐标 地图13 x=4 y=57
- facing: north
- walk_map: 这一屏 10 列 × 9 行；每行末尾括号里是该行首尾两格的全局 x
y=53 ..........  (x=0..9)
y=54 ......####  (x=0..9)
y=55 .....#####  (x=0..9)
y=56 .....#####  (x=0..9)
y=57 ....@.####  (x=0..9)
y=58 ..........  (x=0..9)
y=59 ..........  (x=0..9)
y=60 ..........  (x=0..9)
y=61 ##........  (x=0..9)
```

可调用按键：up、down、left、right、a、b、start。
可调用脚本：face_direction、walk_to_adjacent、walk_to、circle_walk、bounce_in_tall_grass、talk_to_adjacent_npc、interact_facing、advance_dialog、wait_until_scene、exit_map、heal_at_center、open_menu_to。

审核目标：向北走一格。

候选下一步：`{"action": "up"}`

判断：**够**。位置 (4,57)，地形 y=56 的 x=4 为可通行格；按键 up 已开放。没有目标时只能判断能走，不能决定应该往哪走。

## 补充边界检查

- 所有1045帧均完成显示重建。title 和部分开场帧共13帧未加载地图，重建时明确跳过地图读取；这不是生产 perceive_task 已支持无地图的证明。
- 13帧场合解码与未审真值不一致：c-0002, c-0006, c-0007, c-0008, c-0015, c-0049, c-0241, c-0252, c-0380, c-0641, c-0810, c-0865, c-0867。其中5帧 battle_menu 被判为 battle，2帧自愿换人被判为 faint_switch；错误场合会改变脚本路由。
- 2帧场合未定：c-0419、c-0440。不挂任何已确认组合。
- 当前组合代表帧是易读示例，不能代替同组全帧验证。稳定性、被挡、脚本恢复、预算、目标判停必须在实际执行与新观测中核验。
- 普通对话/商店交谈已补 where；shop/none 已补空间信息；bag/none 已保留屏幕以免丢失城镇地图选中地点；无可显示内容时已有明确提示。
- 不以该文档批准新真值，不改冻结帧、ROM 或用户存档，不提交或推送。

## 后续补充的观测字段

`menu_decode_complete` 来自本帧 ScreenText.covered，None 表示未测；只评价选单切分，不评价场合正确性或稳定性。`selected_map_location` 在背包城镇地图中按顶行地名规则提取，不是主角位置；同时显示 where。`observation_notes` 按空文字、切分不全、业务视图缺失、过场分类给出明确限制。普通对话选单也保留 where。新增字段不新增真值评分组，也不推断静态快照是否稳定。
