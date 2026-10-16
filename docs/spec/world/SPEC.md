# world —— 模块规格

> 最后更新：2026-10-08 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

读屏菜单先由screen_layout识别命名键盘、队伍、设置和图鉴的物理布局，再由screen_menu处理普通框选及价格列表。
队伍箭头位于名字下一行，命名结束键ED只在该布局解释；没有实心箭头时不猜光标。
scene_layout提供无地图空屏、独立开场画像和战斗菜单框形证据；完整战斗菜单框即使尚无箭头也可识别。
战斗行动菜单初态另要求实心光标在FIGHT；reset_menu在主菜单用方向键归位，子菜单仍按B退出。
固定帧基线范围、阶段修复及验证证据见docs/DECODER_FIX_1007.md；100%的参考匹配不表示未收录场景或操作流程已验证。

## 2026-10-14 全场合基础按键

`compute_action_space` 在所有 TaskScene 和 overlay 上开放后端支持的 up/down/left/right/a/b，
包括脚本接管场合；脚本继续按场合提供。接管场合的 start/select 仍关闭，非接管
其他键继续按 overlay 给出。covered_by_script 表示可调用业务脚本，不表示禁止基础按键。
键和脚本共享 mask/entries，门面只补 prompt 文案，不改掩码。基础按键可用不保证画面会响应，
严格对话帧可能无效；变化由下一帧证据判断。字段和 Port 形状、解码器、脚本实现不变。

## 2026-10-08 decoder 裁决与现行规则

- 地形精灵按 `C204/C205 + 16*slot - 4` 的地图格位定位，再相对主角转成屏幕格网；移动中的 NPC 取游戏已更新的目标格。`D5CE` 的槽号/全局编号列表与 `D5A6` 的隐藏位图决定是否跳过槽位。招牌、门、精灵的覆盖顺序及图片种类规则不变。`D535=FF` 表示没有草，不生成 G。通行仍取每格左下子图块。
- `ram.map_settled(memory)` 是生产、冻结数据集 `has_map`、coverage 共用的地图适用判据：通行表指针非零，且地图编号在静态表内、地图头 tileset 等于 `D367`。`scripts/build_map_tilesets.py` 从英文红版 ROM 的 `01AE` 地图头指针与 `C23D` 银行表生成 `world/tables/map_tilesets.json`，含 248 个地图编号；运行时只读静态表，不查 ROM 地图头。该判据识别 tileset 不一致的换图过程，不能证明所有同 tileset 换图都已稳定。
- 无字且地图未稳定时为 transition。三层共用的生产观测路径都跳过地形，不沿用上一帧：`place=None`、`map_id=None`、where/facing/neighbors/walk_map 为空、landmarks 为空；当前截图、屏幕解码与 RAM 读数仍照常返回。task 单帧装配在 `task_perception.observe_task`，PyBoyWorld 负责取帧与调用。
- 起名对象由 `D07D` 决定：0 是 YOUR NAME?，1 是 RIVAL's NAME?，其余是 NICKNAME?；前两者最多 7 个字符，昵称最多 10 个。键盘维持 9/9/8/9/9，第三行第九格的空格是真正可输入的键，但产品刻意不提供它。0x76/0x77 在命名布局显示 `_`，其余布局维持 HUD 框线。
- 战斗招式框侧边完整时，恰为 `-` 的行是不可达空位，从选项、排布和附注中去掉，但保留整屏显示；命名键盘的 `-` 仍为可选键。类型说明框可能覆盖招式框左上角，因此不以该角判定框形。
- 无实心光标时仍读取完整商品框。只有末项 CANCEL 可以没有价格，其余商品必须具有完整价格；数量框遮挡或残框不补造选项，不猜光标。
- 图块 FF 只有左右至少一格在 79–FE（边框、空格、文字）时才显示数字 9，否则显示非文字点；没有字表邻居的 FF 达 20 格时先判 transition，再看战斗标志。标题 Logo 第一行第二至十七列的连续 80–8F 图块判 title，整屏为空；没有 80–FF 文字图块且没有完整普通框的图形页也不输出伪 HUD 文字。这一限制保留无框纯数字和符号显示。
- 能力页的 STATUS/、TYPE1/、EXP POINTS 与图鉴条目专用框在战斗判据前识别为 pokemon_info。野外空背包大框须同时有背景开始菜单边角和背包指针；商店 MONEY 布局优先，不误认买卖重绘。完整空开始菜单框判 start_menu；有文字或空心箭头的现有场合不变。
- `covered` 表示已识别布局的选项切分完整，队伍和图鉴列表为 true。光标是否必须紧邻选项由独立的 `cursor_adjacent` 参数决定，图鉴列表箭头第零列、选项第四列仍能正确匹配。
- 图块 74 紧接 F2 时显示 `No` 再加后面的点，战斗中也显示 No.；74 直接接数字时沿用原规则。
- 依赖核对识别 direct/mcpclient 门面与指定 world MCP 服务适配器（world_server.py、world_server_cli.py）；其他服务、harness、schemas 不得依赖 world 实现，world 对其他项目模块的出边仍为零。

验证限定于 1045 个冻结帧，不能替代留出集与模拟器操作测试；数据集未覆盖的小写键盘、异常状态或三只以上队伍、非空 PC 箱、忘招列表等仍未验证。

## 一、职责与边界

world 是 `WorldPort` 的唯一实现：把 PyBoy 模拟器、内存读取与屏幕字符缓冲解码组成可推进、可观测的世界。
观测只有 `perceive_task` 一档，不调用模型。坐标、地形、战斗与队伍来自游戏变量；对话、选项、光标来自字符缓冲。

边界四条：

- **出边为零**：`world/` 包内不 import `pokemon_agent` 的其余部分（第八节有可执行核对）。
- **不认识信封**：Port 收/吐裸字段与 world 自己的形状，不认本项目的 `*Req` 信封。
- **不做判定**：不知道任务目标，不算"这一局该不该结束"；`Observation.done` 只回答"世界还在不在"。
- **不写 trace**：观测与截图交给 tool 层，再由 harness 写账。

## 二、目录结构

```
world/
├── __init__.py                  统一出口：interface 立即加载，pyboy_world/ram 经 _LAZY 表懒加载
├── errors.py                    WorldError（根）
├── pyboy_world.py               ALL_BUTTONS、节奏常量、PyBoyWorld
├── ram.py                       读内存：read_facing / read_passable / read_screen_tiles / read_terrain
├── screen_text.py               读屏幕文字：wTileMap(0xC3A0) 按英文版字符表解码 → 对话 / 选项 / 光标 / 排布 /
│                                选项附注（× 数量、¥ 价格）/ 覆盖判定；光标字节 0xED、战斗标志 wIsInBattle(0xD057)
├── battle_status.py             read_battle_status：战斗双方名字 / 等级 / HP / 状态（游戏变量）
├── readout.py                   read_readout：一帧的 RamReadout（菜单变量、金钱、背包、队伍、战斗、文字来源）
├── scene.py                     classify_scene / at_start：task 层的场合分类与脚本初态判断（纯函数）
├── items.py                     item_name / item_id（不分大小写、é = e）/ item_price（ROM ItemPrices 0x4608，3 字节 BCD）
├── moves.py                     move_name / fold（名字比对的规范形）
├── tables/items.json            道具编号 → 名字
├── tables/moves.json            招式编号 → 名字
├── action_space.py              compute_action_space：按这一帧的 overlay / 场合算统一能力掩码（键 + 脚本）
├── scripts/                     脚本层（一次调用执行到底、占 harness 账一步）
│   ├── catalog.py               SCRIPT_SPECS / SCENE_SCRIPTS / 按名调用；所有结果都是 ScriptResult
│   ├── interface.py             唯一 WorldConsole 协议（含 run_script：脚本组合）
│   ├── engine.py                唯一 ScriptRun：共用按键、等待、事件、步骤与终态报告
│   ├── definitions.py           ScriptDefinition / run_definition：执行显式声明的生命周期
│   ├── policies.py              ScriptPolicy / StableWait：等待、中断、准备、恢复与收尾配置
│   ├── interruptions.py         可组合的战斗、选项、换图中断条件
│   ├── screen_wait.py / screen_steps.py / timing.py
│   │                            共用稳定等待、文字推进、光标导航与私有帧预算
│   ├── control_flow.py / execution_types.py / dialog_cache.py / tables.py
│   │                            ScriptResult、具名停止信号、步骤类型、对话增量和静态表
│   ├── console_adapter.py       PyBoyWorld → WorldConsole
│   ├── movement.py / interact.py / flow.py / menu.py / navigation.py / shop.py
│   │                            按业务组织的脚本；不是另一类执行器
│   └── takeover/                菜单、战斗等场合的脚本声明与视图
│       ├── __init__.py          PREFIX / REGISTRY / SCRIPT_DEFINITIONS / takeover_view
│       ├── policy.py            初态恢复、严格等待与可选收尾的组合配置
│       ├── common.py            共用读数（队伍、背包、药的分类与效果预判）与操作（选项光标、列表光标、数量、YES/NO）
│       ├── shop.py              shop_items 场合：buy / sell / quit、shop_view
│       ├── naming.py            naming 场合：enter_name、naming_view
│       ├── battle.py            battle_menu 场合：fight / switch / use_item / run、battle_view；
│       │                        battle_switch 场合：send_out、switch_view
│       ├── bag.py               bag 场合：use / toss / close、bag_view
│       ├── party.py             party 场合：switch / field_move / stats / close、party_view
│       ├── pc.py                pc 场合：withdraw_item / deposit_item / toss_item / withdraw_pokemon /
│       │                        deposit_pokemon / change_box / log_off、pc_view
│       └── learn_move.py        learn_move 场合：forget / skip、learn_view
├── interface/
│   ├── __init__.py              统一出口（协议 + 数据形状 + 常量）
│   ├── world_port.py            WorldPort 契约（7 个方法）
│   ├── memory.py                Memory 协议（按地址取字节）
│   └── domain/
│       ├── __init__.py          统一出口
│       ├── action_semantics.py  BUTTON_FACING / FACING_STEP / DIRECTION_KEYS / INTERACT_KEY
│       ├── action_space.py      ActionSpace（mask / entries；键 names 只在开放按键的场合非空）
│       ├── action_entry.py      ActionEntry（kind ∈ key / script，签名 signature()）
│       ├── script_param.py      ScriptParam（脚本参数：name / type / description / default）
│       ├── takeover_view.py     八个接管视图（ShopItemsView / NamingView / BattleMenuView / BattleSwitchView /
│       │                        BagView / PartyView / PcView / LearnMoveView，各有 render()）、
│       │                        MonEntry / MoveEntry / BoxEntry、TakeoverView（按 kind 区分的联合）
│       ├── battle_status.py     BattleStatus / Combatant（facts_fields() 给 my_* / foe_* 字段）
│       ├── ram_readout.py       RamReadout / MenuVars / BagItem / PartyMon / DecodedText / TextSource（只进 trace）
│       ├── facts.py             Facts（内部类 Scene/Overlay/Landmark）+ OVERLAY_ACTIONS
│       ├── observation.py       Observation
│       ├── place_in_world.py    PlaceInWorld
│       ├── screen_model.py      网格常量、地形字符、TERRAIN_MEANING、terrain_legend
│       ├── screen_text.py       ScreenText（dialog_text / options / cursor / option_grid / cursor_cell /
│       │                        option_details / covered + render_layout() / render_details()）
│       ├── task_scene.py        TaskScene（task 层场合词表）、SCRIPT_ONLY_SCENES
│       ├── task_observation.py  TaskObservation（Observation + scene + takeover + covered_by_script）
│       ├── terrain_map.py       TerrainMap
│       └── task_perceived.py    TaskPerceived（观测、截图与 RAM 读数）
├── task_perception.py           observe_task：装配内存观测
└── frame_encoding.py            png_data_uri：截图编码
```

`world/__init__.py` 统一导出公开形状；`PyBoyWorld` / `read_facing` / `read_passable` / `read_screen_tiles` / `read_terrain` / `classify_scene` / `at_start` 走 `_LAZY` 表懒加载（`pyboy_world` 拽着 `pyboy`），其余（`interface/` 的协议与数据形状）立即加载。

## 三、WorldPort 契约

`world/interface/world_port.py`，`@runtime_checkable` 的 `Protocol`，**7 个方法**：

| # | 方法 | 签名 | 前置条件 | 承诺 | 失败方式 |
|---|---|---|---|---|---|
| 1 | `reset` | `(*, task_id: str, goal: str, success_criteria: str, max_steps: int, initial_state_hint: str = "") -> None` | `max_steps > 0` | 按任务重置到初始状态，**不感知**——第一帧由调用方另调 `perceive_task()` | 实现里 `assert max_steps > 0`；`state_path` 缺失在构造期就 `FileNotFoundError` |
| 2 | `all_actions` | `() -> list[str]` | 无 | 非空，且整个 episode 内不变 | 不失败 |
| 3 | `step` | `(segments: list[tuple[str, int]], *, settle: bool = True) -> None` | 每一段的按键都在 `all_actions()` 中；当前 episode 未结束 | 按序执行按键段，推进世界，**不感知** | 按键不在 `ALL_BUTTONS` 是调用方 bug，assert 拦下；实现另断言"已 `reset()`""窗口没关" |
| 4 | `perceive_task` | `() -> TaskPerceived` | 已 `reset()` | 三层共用：只读内存与屏幕缓冲，`TaskObservation` 带场合与接管视图 | 不失败 |
| 5 | `save_state` | `() -> bytes` | 无 | 模拟器完整状态（CPU / 内存 / 画面）的字节串，非空；**不推进世界** | 不失败 |
| 6 | `load_state` | `(data: bytes) -> None` | `data` 是 `save_state` 的产物 | 恢复到导出那一刻；**读档后不 tick**（09-25 实测读档即恢复画面与内存，多 tick 一帧内存就偏离） | 数据非法时 PyBoy 原样抛出 |

两个要点：**裸字段**——`reset` 收 `Task` 拆开后的五个原始值、`step` 收 `Action.sequence` 拆开的 `(按键名, 连按次数)` 列表，world 不依赖 brain 的类型。
**`settle` 只改调用方什么时候拿到控制权**，不改按键本身的效果：`True` 等"按下去之后自己走完"的过程（换图淡入淡出 / 战斗开场 / 对话逐字打出 / 菜单弹出）走完；`False` 按完即返回，链中间的键用这一档，代价是可能抄到过场的中间帧。

实现类 `PyBoyWorld` 另有两个不在 `WorldPort` 里的方法：`stop()` 与 `evolve(frames)`
（`assert frames >= 0`）——见第九节。

## 四、世界语义常量

**按键与方向**（`pyboy_world.py` / `action_semantics.py`）：

| 常量 | 值 |
|---|---|
| `ALL_BUTTONS` | `("a", "b", "up", "down", "left", "right", "start", "select")` |
| `INTERACT_KEY` | `"a"`（作用在**面朝的那一格**上） |
| `DIRECTION_KEYS` | `frozenset(BUTTON_FACING)`，即 `{"up","down","left","right"}` |
| `BUTTON_FACING` | `up→north`、`down→south`、`left→west`、`right→east` |
| `FACING_STEP` | `north (0,-1)`、`south (0,1)`、`west (-1,0)`、`east (1,0)`（y 向下增大） |

`OVERLAY_ACTIONS`（`facts.py`，非接管按键的基础集合）：`NONE` / `CHOICE` → `("up", "down", "left", "right", "a", "b", "start")`；`DIALOG` → `("a",)`。`compute_action_space` 再把后端支持的基础按键（四个方向键、a、b）并入所有场合和叠加层；脚本接管场合保留基础按键和本场合脚本、关闭 start/select。
`pyboy_world.py` 在**导入时**断言 `OVERLAY_ACTIONS` 里出现的每个键都属于 `ALL_BUTTONS`。

**地形与网格**（`screen_model.py`）：`GRID_COLS = 10`、`GRID_ROWS = 9`（注释：160/16 = 10，144/16 = 9）、`PLAYER_CELL = (4, 4)`（镜头锁在主角身上，是常量）、`PLAYER_MARK = "@"`、`DOOR, SIGN, PERSON, ITEM, BOULDER, GRASS = "D", "S", "N", "I", "B", "G"`、`MAP_CHARS = frozenset(TERRAIN_MEANING)`。
`TERRAIN_MEANING` 的九个键：`"."` 能走、`"G"` 草丛、`"D"` 门、`"S"` 招牌、`"N"` 人、`"I"` 物、`"B"` 巨石、`"#"` 墙、`"@"` 你自己；`terrain_legend()` 把它渲染成 prompt 图例。

**内存地址**（`ram.py`，全是《宝可梦 红》的）：`W_TILEMAP = 0xC3A0`、
`SCREEN_COLS, SCREEN_ROWS = 20, 18`、`W_CUR_MAP = 0xD35E`、`W_Y_COORD = 0xD361`、
`W_X_COORD = 0xD362`、`W_COLLISION_PTR = 0xD530`、`W_GRASS_TILE = 0xD535`、
`W_NUM_WARPS = 0xD3AE`、`W_NUM_SIGNS = 0xD4B0`、`W_SPRITES = 0xC100`、
`SPRITE_STRIDE = 16`、`FIRST_STILL_SPRITE = 0x3D`、`SUB_TILE = (0, 1)`（取左下子格查通行表）、
`FACING_BY_BYTE = {0: "south", 4: "north", 8: "west", 12: "east"}`（精灵表 +9）。

**按键节奏**（`pyboy_world.py`，`GB_FPS = 60` 是换算基准）：`PRESS_FRAMES = 10`
（`pyboy.button(name, delay=…)` 按住多少帧）、`WITHIN_ACTION_FRAMES = 1 * GB_FPS` = 60
（每次按完推进多少帧）、`AFTER_ACTION_FRAMES = 10 * GB_FPS` = 600（`settle=True` 时整条链
按完再推进多少帧）、`BOOT_FRAMES = 10 * GB_FPS` = 600（无存档时空转多少帧越过开机 logo）。

**其他常量**：`_EXTRA_ORDER`（`facts.py`）定义事实字段的渲染顺序。

## 五、数据形状

| 形状 | 谁产出 | 谁消费 | 关键字段 |
|---|---|---|---|
| `Observation` | 内存观测的基础类型 | `TaskObservation`、旧账兼容读取 | `step`（占位 0，由 Harness 盖章）、`place: PlaceInWorld \| None`、`status`、`facts: Facts`、`done`；方法 `stall_key()` / `render(indent="  ")` |
| `TaskObservation` / `TaskPerceived` | `PyBoyWorld.perceive_task()`（`task_perception.observe_task`） | run / episode / task：`GameTools.perceive_task` → `FromHarnessToGameToolPerceiveTaskResp`、`TaskState`、决策 / 反思 / 掩码 / 执行的信封、`sense_frame` 账（正文带 `scene`）、ActMemory 的前后帧（`scene` 字段） | `Observation` 的全部字段 + `scene: TaskScene`（场合，必有）+ `takeover: TakeoverView \| None`（脚本接管场合给视图）+ `covered_by_script: bool`（从场合派生的只读接管覆盖标志）。三层状态都声明为 `TaskObservation`，序列化保留 scene/takeover；`scene` 与 `Facts.Scene` 是不同字段 |
| `TaskScene` / `SCRIPT_ONLY_SCENES` | `scene.classify_scene()` | task 层、读屏测评 | 16 类场合，见 `docs/perceive/spec.md` 第三节 |
| `Facts` | `PyBoyWorld` 拼装 | harness 交互判定、`direct/prompts`、记忆检索 query | 具名 `scene`/`overlay`/`where`/`facing`/`neighbors`/`landmarks`/`dialog_text`/`options`/`cursor`/`walk_map`/`map_id`；`extra="allow"` 接住内存派生的额外字段；`scene_value` / `overlay_value` / `exclude(keys)` / `items()` / `stall_key_part()` / `render()` |
| `Facts.Scene` | 内存战斗标志（战斗或空） | 掩码与 prompt | `FIELD` `INDOOR` `BATTLE` `MENU` `SHOP` `TRANSITION` |
| `Facts.Overlay` | 屏幕字符缓冲解码 | `OVERLAY_ACTIONS` 的键 | `NONE` `DIALOG` `CHOICE` |
| `Facts.Landmark` | `TerrainMap.landmarks()` | harness 交互判定 | `kind`（`KIND_DOOR`/`KIND_SIGN`/`KIND_PERSON`/`KIND_ITEM`/`KIND_BOULDER`）、`map_id`、`x`、`y`；属性 `place` 现场拼 `PlaceInWorld` |
| `PlaceInWorld` | RAM 读出的坐标 | 记忆的键、交互判定 | `map_id` / `x` / `y`；`step_toward(facing)`、属性 `key` = `"{map_id}:{x}:{y}"`、`render()` |
| `ActionSpace` | `compute_action_space()`（掩码的唯一出处；`mcpclient/game_tools.py::_action_space()` 只在其上补 prompt 文案） | brain（`ChooseOnceReq`） | `mask` / `entries: list[ActionEntry]` / `names` / `descriptions` / `note` / `map_note`（所有场合开放基础按键，脚本接管场合另外开放业务脚本，start/select 仍关闭）；`contains(name)` / `enabled(name)` / `entry(name)` |
| `ActionEntry` / `ScriptParam` | `scripts/catalog.py`（脚本）、`scripts/scenes/` 各场合文件（脚本） | tool 层：动作空间、prompt 的脚本签名与说明、转成 brain 的 `ScriptSignature` | `kind`（`key` / `script`）/ `name` / `params`（`name` / `type`∈{str,int} / `description` / `default`，None = 必填）/ `description`；`signature()` 写成 `buy_item(item: str, count: int)` |
| `TakeoverView` | `scripts.scenes.takeover_view()`（`task_perception.observe_task` 里） | `TaskObservation.takeover` → 脚本接管场合的决策 prompt、`sense_frame` 账 | `ShopItemsView`（`items` 名字与价格、`money`、`bag`）/ `NamingView`（`target` 屏幕标题、`typed` 已输入）/ `BattleMenuView`（`mine` 在场那只带招式与剩余 PP、`foe`、`trainer`、`party`、`bag`）/ `BattleSwitchView`（`party`）/ `BagView`（`bag`、`party`）/ `PartyView`（`party`）/ `PcView`（`items` PC 道具、`bag`、`box` 当前箱、`box_number`、`party`）/ `LearnMoveView`（`pokemon`、`new_move`、`moves`）；队员是 `MonEntry`（昵称、等级、HP、状态、是否在场、招式）；`render()` 给 prompt 几行 |
| `RamReadout` | `readout.read_readout()` | 经 tool 层写进 `sense_frame` 账的 `ram`；**不进 agent 输入**，测评读它 | `in_battle` / `covered` / `text_source`（当前为 `decode`，`vlm` 仅兼容旧账）/ `menu: MenuVars` / `money` / `bag: [BagItem]` / `party: [PartyMon]` / `battle: BattleStatus \| None` / `decoded: DecodedText`（每帧的屏幕解码结果，供机械判据读取） |
| `BattleStatus` | `battle_status.read_battle_status()`（不在战斗时 `None`） | `Facts` 的额外字段（`facts_fields()`）、`RamReadout.battle` | `mine` / `foe: Combatant`（`name` 取 RAM 昵称字段、`level`、`hp`、`max_hp`、`status`） |
| `TerrainMap` | `ram.read_terrain()` | `PyBoyWorld` 拼 `Facts` | `cells`（9 行 × 10 字符，构造时校验形状与字符集）/ `map_id` / `player_x` / `player_y` / `facing` / `ambiguous_cells`；`at()` / `neighbors()` / `render()` / `landmarks()` / `place()` / `render_neighbors()` |
| `Memory`（Protocol） | —— | `ram.py` 的四个读函数 | `__getitem__(addr: int \| slice)`，只要能按地址取字节，不必是真 PyBoy |

## 六、感知链路

`PyBoyWorld.perceive_task()` 读取截图、游戏变量与屏幕字符缓冲，经 `task_perception.observe_task`
装配 `TaskPerceived`（`TaskObservation`、frame_png、ram）。run、episode、task 三层都经
`harness.sensing.perceive_task` 使用它，不调模型、不产模型调用账；截图仍可交给 brain 的多模态判定通道。

- 游戏变量提供位置、地图、朝向、地形、地标、战斗状态、队伍与背包。
- 屏幕解码提供整屏文字、对话、选项、光标、排布和 overlay；`scene.classify_scene` 提供 `TaskScene`。
- `Facts.scene` 仍为战斗或空，知识检索用 `TaskObservation.scene.value` 作为场景键。
- 屏幕有字时给 screen，没字时给 walk_map；地图未稳定不沿用旧地形。
- 观测本身不含 perceived 或 overview。旧记忆的兼容字段由 memory 的快照形状负责。
- 三层 sense 节点记录 sense_frame；sense_call 已停止产出，旧账仍可读。

- **整屏渲染**：一个图块一个字符；边框 `┌─┐│└┘`（含战斗 HUD 框线 0x6F / 0x76–0x78）、等级 `:L`、
  血条 `HP:[██████]`（每格 8 像素按填充渲染）、`ID` / `No.` 只在战斗外渲染，其余非文字图块 `·`。
  `:L` / `HP:` 一个图块占两三个字符，所在行后面的列会右移。整屏既没字也没边框（走路、过场）时给空串。
  记忆快照存 `screen`，历史渲染（`ActMemory._render_obs`）也保留它（只去掉 `walk_map`），judge / verify 看得到。
- **叠加层**（`screen_text.overlay_of`）：屏幕上有 `▶`、数量框（`×` 紧跟两位数字）或完整商品价格列表→ CHOICE；
  严格的对话帧（`ScreenText.strict_dialog`：底部对话框画着（空框也算）、没有 `▶`、没有数量框、对话框外没有别的框）→ DIALOG；
  图鉴条目页下半的说明框（图鉴专用边框图块 0x66–0x6F）按对话框读，说明文字进 `dialog_text`；
  其余 NONE。这里表达按键控制模式，不是窗口是否重叠。
  菜单定位与提取在 `screen_menu.py`，无箭头的完整商品框由 `priced_menu.py` 读取商品、排布与价格；
  数量框遮挡、边框不完整或价格不齐时不补造完整列表，无箭头时 cursor 为空、cursor_cell 为 null。
  战斗中的队伍选择统一为 battle_switch，主动换人与倒下换人不按HP区分场合；两者只提供同一个换人脚本和队伍视图。野外队伍列表仍是 party，战斗用道具选对象仍属于 battle_menu。
- **掩码**：所有场合开放后端支持的上下左右、a、b；非接管 NONE 与 CHOICE 另外给 `start`，DIALOG 和接管场合不给 start；所有场合不给 select——
  叠加层判错的代价只是多几个当帧无效的键。
- **测评**：`RamReadout.decoded` 每帧都记（三层），机械判据只读它；`covered` 只做统计。

transition 场合开放 `wait_until_scene(scene: str, timeout_s: int=10)`，只推进帧、不按键；目标场合匹配即返回 ok，超时返回 timeout 并带当前场合，task 随后重新感知。目标匹配不保证稳定，目标应按任务上下文指定。标题菜单按用户保证不进入生产运行范围，冻结标题帧只作为历史解码样本，不要求本轮补无地图感知入口。

## 七、脚本（`scripts/scenes/`）

`covered_by_script=true` 表示本帧属于已有脚本覆盖的场合；子菜单与数量框仍为 true，与 `at_start` 无关。开放按键的场合即使提供导航等可选脚本也为 false。该字段从 `SCRIPT_ONLY_SCENES` 派生并随 task 观测序列化，动作空间核对实际脚本注册表与词表一致。模型直接选择目标脚本，由脚本尝试恢复初态后执行；恢复与执行可能失败，必须读返回结局。

TaskObservation 另带 `menu_decode_complete: bool | None`（生产取 ScreenText.covered，None=未测，仅评价选单切分）、`selected_map_location: str | None`（背包城镇地图顶行唯一地点，当前屏幕派生，非主角位置）、`observation_notes: list[str]`（空文字、切分不全、业务视图缺失、过场的限制说明，当前观测派生）。地图选中地点与 where 同时显示，替代重复的整屏图形；普通对话选单也显示 where。选单完整性只在 choice 或不完整时显示；正常走路不重复提示没有文字。单帧不产出稳定性或置信度字段。

task 决策的当前帧显示由 `direct/prompts/task_frame.py` 按场合与叠加层投影，不改变完整观测、历史记忆或 decode 输出。开放按键的帧显示 task `scene`、`covered_by_script`、`overlay`；walk/none 与 shop/none 给位置、朝向、地标与地形（网格与四邻择一），纯对话给对话文字，dialog/shop 交谈另保留地点，选单和信息页优先给整屏文字以避免切分遗漏，不重复列 options/cursor/layout。战斗文字保留双方状态。脚本接管帧显示覆盖标志、业务视图、overlay、已解码光标及整屏文字以支持方向键导航；缺业务视图时用整屏文字兜底，不显示地形或 at_start。整屏显示只省略空白行和行尾空格；无可显示内容时明确提示不能据此判断界面结束。目标、合法动作和上一脚本结果继续由各自段落提供。实际帧组合与静态下一步核对见 `docs/SCENE_OVERLAY_EXAMPLES_1007.md`，不代替模型选择与脚本执行验证。

脚本接管场合里 JEV 可以用基础按键导航，或选一条带参数的业务脚本；选择脚本时由 world 执行到底。所有脚本统一使用脚本动作
（`ActionEntry`，`kind="script"`，经 `GameTools.execute` 的脚本通道执行，记 `act_call` script 形），
差别在可用场合和脚本选择的规则，执行现场相同。**对外名 = 场合前缀 + 文件内短名**（`shop_quit` = `shop` + `quit`），
前缀表 `scenes.PREFIX` 是唯一规则。每个场合一个文件，每条只写**前提校验 + 执行 + 收尾**，
这些脚本通过 `definitions.run_definition` 执行显式声明的 `menu_policy`：

1. **认场合、找脚本、核参数类型**：场合不是脚本接管场合或本场合没有这条 → `rejected / unknown_script`；缺参数、类型不对 → `rejected / bad_args`（一个键都不按）。
2. **回初态**：等画面与玩家位置稳定（每 `POLL_FRAMES` 帧读一次、连续 `STABLE_POLLS` 次相同，忽略闪烁的 `▼`，并满足策略声明的最短等待）→ `at_start` 真则进 3；场合已变 → `left_scene`；否则按 B，最多 `REWIND_LIMIT` 次（超了 `aborted / rewind_limit`）。
3. **按此刻内存校验前提**（钱、背包、商品、持有数、名字字符与长度、招式与 PP、队员）→ 不满足 `rejected`，原因码见 `ScriptReason`（商店与起名：`unknown_item` `not_enough_money` `bag_full` `quantity_out_of_range` `not_in_bag` `key_item` `invalid_name`；战斗：`unknown_move` `no_pp` `unknown_pokemon` `pokemon_fainted` `already_active` `target_required` `cannot_use`；通用：`unknown_script` `bad_args` `rewind_limit` `step_timeout` `unexpected_screen`）。
4. **执行**：每一步按键后等稳定、核对期望（`wait_for` 只在没有光标、没有数量框时按 A 推进文字）；没出现期望 → 回初态、`aborted`。
5. **收尾**：回初态（离开场合的脚本不回），`done` 带一行 `summary`（如 `钱 3000→2000，POKé BALL +5`）。

执行直接返回统一的 `ScriptResult`：`ok` = `done`；`code` = `ok` / 原因码 / 结局。
菜单脚本的 `data` 带 `scene` / `status` / `reason` / `summary` / `steps`；逐步明细由脚本的 `record_steps` 配置启用。
所有脚本只经同一个 `WorldConsole` 协议碰模拟器。`ScriptRun` 不默认启用三种中断；地图操作脚本选择 `field_policy`，菜单操作脚本声明严格等待、初态恢复和收尾。开始菜单导航与回血确认同样使用这个执行器，其步骤明确不启用选项中断。

| 场合 | 脚本（对外名） | 视图 |
|---|---|---|
| `shop_items` | `shop_quit()`；买卖走带白名单与终态对账的脚本 `buy_item(item, count)` / `sell_item(item, count)`，它们经 `console.run_script` 组合调用内部的 `shop_buy` / `shop_sell`（这两条不单独给模型） | `ShopItemsView` |
| `naming` | `naming_enter_name(name)`（只收大写字母，长度 ≤ 7，`NICKNAME?` ≤ 10） | `NamingView` |
| `battle_menu` | `battle_fight(move)`、`battle_switch(pokemon)`、`battle_use_item(item, pokemon="")`、`battle_run()` | `BattleMenuView` |
| `battle_switch` | `switch_send_out(pokemon)` | `BattleSwitchView` |
| `bag` | `bag_use(item, pokemon="")`、`bag_toss(item, quantity)`、`bag_close()` | `BagView` |
| `party` | `party_switch(a, b)`、`party_field_move(pokemon, move)`、`party_stats(pokemon)`、`party_close()` | `PartyView` |
| `pc` | `pc_withdraw_item` / `pc_deposit_item` / `pc_toss_item(item, quantity)`、`pc_withdraw_pokemon` / `pc_deposit_pokemon(pokemon)`、`pc_change_box(n)`、`pc_log_off()` | `PcView` |
| `learn_move` | `learn_forget(move)`、`learn_skip()` | `LearnMoveView` |

**战斗脚本的收尾是自动推进战斗文字**（`ScriptRun.advance`）：只在屏上出现 `▼`（游戏在等按键）、或画面静止满
`QUIET_PRESS_FRAMES`（300）帧时按 A——文字自己在走时按早了会落在紧接着出现的选单上；遇到任意 `▶`
（下一个选单、单层 YES/NO 如 "Use next POKéMON?"、抓到后的起名询问）或战斗标志清零即停，按满 `ADVANCE_LIMIT` 次或
空等满 `ADVANCE_WAIT_FRAMES` 帧也停。停在战斗选单的子层时按 B 退回行动菜单。摘要写双方 HP 变化与停在哪。
前提：`fight` 招式在在场宝可梦身上且有 PP；`switch` / `send_out` 目标在队伍里、没倒下（`switch` 还要不在场）；
`use_item` 背包里有，球只在野战，伤药 / 解异常 / 复活要给对象且对它有效，X 系列不给对象；`run` 只在野战。
球的抓捕流程走完才从背包扣，所以球只报抓没抓到，其余道具核背包少一个。

**野外的几个场合**：`use` 支持药（能预判没效果的先拒）、进化石、营养剂、RARE CANDY（选对象）与驱虫喷雾，
其余道具拒掉；用完推话直到下一个 `▶`（背包列表、学新招的 YES / NO……）——换画面时有几百帧整屏空白，只认光标。
`field_move` 不支持 FLY（要再选目的地）；没用成（缺徽章、面前没有树）以 `aborted` 带回游戏的原话。
PC 道具走主角的 PC、宝可梦与换箱走比尔的 PC；打开时 "Accessed …" 那几句话显示时主菜单光标还画着，要替它推；
换箱时游戏会存档，画面静止几百帧（`ScriptRun.idle_until` 不按键干等）。
学新招时忘不掉的秘传招式以"没有学会"`aborted`；学招提示前的几句（`trying to learn` / `can't learn more` /
`than 4 moves`）也归 `learn_move`，回初态时按 B 推过去。
测评：`world_actions` 共 106 例，经统一脚本入口核自报与世界真值；`decode` 从冻结帧核菜单视图。
## 八、依赖边界与自包含核对

**出边为零**：`world/` 内唯一的绝对 import 是 `from pokemon_agent.world import …`
（`pyboy_world.py:26`），其余全是相对 import。⇒ 整个 `world/` 拷进另一个项目仍能跑。

**谁能碰实现**：门面层与指定的 world MCP 服务适配器。`GameTools.build()` 创建 `PyBoyWorld`；
其余消费者通过 Port 或公开数据形状取值。world 不依赖 brain，也不持有模型 provider。

**核对脚本**：`python scripts/check_world_self_contained.py`（退出码 0 = 全过），查三类：

- **A〔出边为零〕**：`world/` 包内**没有任何文件** import `pokemon_agent` 的其余部分
  （相对 import 先按 PEP 328 解析成绝对名再判）。
- **B〔实现面只在 `tools/`〕**：`world/` 与 `tools/` 之外的 `.py` 只许 import
  `pokemon_agent.world` 与 `pokemon_agent.world.interface*`；白名单式——新增一个
  `world/xxx.py` 默认就是"实现面"，要放行得改 `ALLOWED_OUTSIDE_TOOLS`。
- **C〔装配点零 import〕**：`build.py` 一个字都不许 import `pokemon_agent.world`
  （`GameTools.build()` 在 tool 层）。

末尾另打印一份**账本**（不算失败）：非 tool 侧对 world 数据形状的 import 点，当前 **12 处**
（`harness/episode` 4、`schemas/harness/communication` 8）。`AGENTS.md` 第十二节第 4 条登记的
14 处是旧计数，以脚本输出为准。脚本只看 import 语句，不看 docstring 散文。

## 九、当前状态与已知缺口

**已成立**：A/B/C 三类约束全过（脚本实测）；三层统一内存观测与整屏渲染已落地；`WorldPort` 由 `PyBoyWorld` 唯一实现，
方法签名与第三节的契约表一致。

**已知缺口**（均不影响运行，但读代码时会被误导）：

- `_Task` 的 docstring 写"`reset()`/`set_task()` 收到的裸字段"，但 `WorldPort` 与
  `PyBoyWorld` **都没有 `set_task()`**。
- `evolve()` 的 docstring 自称"仍是 `WorldPort` 契约的一部分"，但 `world_port.py`
  只声明了 7 个方法，**没有声明 `evolve`**；它当前的唯一调用方是
  `mcpclient/game_tools.py::GameTools.evolve`。
- `TerrainMap.cells` 的字段说明引用
  `pokemon_agent.schemas.world.domain.screen_model.MAP_CHARS`——该路径已无对应文件
  （`pokemon_agent/schemas/world/` 只剩空的 `communication/`、`domain/` 两个目录），
  常量实际住在 `world/interface/domain/screen_model.py`。
- `facts.py` 顶层那段导入顺序说明、`terrain_map.py` 模块 docstring 引用的
  `schemas/world/domain/observation_from_world.py` 同样已不存在；代码里"运行时才 import"
  的写法仍然保留着。
