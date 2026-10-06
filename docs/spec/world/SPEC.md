# world —— 模块规格

> 最后更新：2026-09-26 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

world 是 `WorldPort` 的唯一实现：把 PyBoy 模拟器与视觉模型粘成"一个可推进、可观测的世界"，
外加这个世界自己的语义常量（按哪个键、往哪个方向、哪个键算互动、地形字符什么意思）。

一帧画面变成 `Observation` 要经过两条来源，各管一段，互不替代（`world/pyboy_world.py` 的模块
docstring）：`world/ram.py` 给出坐标、地图编号、朝向、地形通行图、门与招牌的位置——确定，不会
读错；视觉模型给出场景类别、对话框文字、屏幕上有什么——会读错，所以要记账。

边界四条：

- **出边为零**：`world/` 包内不 import `pokemon_agent` 的其余部分（第八节有可执行核对）。
- **不认识信封**：Port 收/吐裸字段与 world 自己的形状，不认本项目的 `*Req` 信封。
- **不做判定**：不知道任务目标，不算"这一局该不该结束"；`Observation.done` 只回答"世界还在不在"。
- **不写 trace**：模型调用记录随 `Perceived.calls` 交给 tool 层，world 侧不攒缓冲区。

## 二、目录结构

```
world/
├── __init__.py                  统一出口：interface 立即加载，pyboy_world/ram 经 _LAZY 表懒加载
├── errors.py                    WorldError（根）/ PerceptionAttemptFailed（唯一子类）
├── pyboy_world.py               ALL_BUTTONS、节奏常量、parse_screen、PyBoyWorld
├── ram.py                       读内存：read_facing / read_passable / read_screen_tiles / read_terrain
├── screen_text.py               读屏幕文字：wTileMap(0xC3A0) 按英文版字符表解码 → 对话 / 选项 / 光标 / 排布 /
│                                选项附注（× 数量、¥ 价格）/ 覆盖判定；光标字节 0xED、战斗标志 wIsInBattle(0xD057)
├── battle_status.py             read_battle_status：战斗双方名字 / 等级 / HP / 状态（游戏变量）
├── readout.py                   read_readout：一帧的 RamReadout（菜单变量、金钱、背包、队伍、战斗、文字来源）
├── scene.py                     classify_scene / at_start：task 层的场合分类与接管脚本初态判断（纯函数）
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
│       ├── __init__.py          PREFIX / REGISTRY / TAKEOVER_SCRIPTS / takeover_view
│       ├── policy.py            初态恢复、严格等待与可选收尾的组合配置
│       ├── common.py            共用读数（队伍、背包、药的分类与效果预判）与操作（选项光标、列表光标、数量、YES/NO）
│       ├── shop.py              shop_items 场合：buy / sell / quit、shop_view
│       ├── naming.py            naming 场合：enter_name、naming_view
│       ├── battle.py            battle_menu 场合：fight / switch / use_item / run、battle_view；
│       │                        faint_switch 场合：send_out、faint_view
│       ├── bag.py               bag 场合：use / toss / close、bag_view
│       ├── party.py             party 场合：switch / field_move / stats / close、party_view
│       ├── pc.py                pc 场合：withdraw_item / deposit_item / toss_item / withdraw_pokemon /
│       │                        deposit_pokemon / change_box / log_off、pc_view
│       └── learn_move.py        learn_move 场合：forget / skip、learn_view
├── interface/
│   ├── __init__.py              统一出口（协议 + 数据形状 + 常量）
│   ├── world_port.py            WorldPort 契约（8 个方法）
│   ├── vision_provider.py       VisionProvider 协议（describe）
│   ├── memory.py                Memory 协议（按地址取字节）
│   └── domain/
│       ├── __init__.py          统一出口，__all__ 59 个名字
│       ├── action_semantics.py  BUTTON_FACING / FACING_STEP / DIRECTION_KEYS / INTERACT_KEY
│       ├── action_space.py      ActionSpace（mask / entries；键 names 只在常规场合非空）
│       ├── action_entry.py      ActionEntry（kind ∈ key / script，签名 signature()）
│       ├── script_param.py      ScriptParam（脚本参数：name / type / description / default）
│       ├── takeover_view.py     八个接管视图（ShopItemsView / NamingView / BattleMenuView / FaintSwitchView /
│       │                        BagView / PartyView / PcView / LearnMoveView，各有 render()）、
│       │                        MonEntry / MoveEntry / BoxEntry、TakeoverView（按 kind 区分的联合）
│       ├── battle_status.py     BattleStatus / Combatant（facts_fields() 给 my_* / foe_* 字段）
│       ├── ram_readout.py       RamReadout / MenuVars / BagItem / PartyMon / DecodedText / TextSource（只进 trace）
│       ├── facts.py             Facts（内部类 Scene/Overlay/Landmark）+ OVERLAY_ACTIONS
│       ├── observation.py       Observation、BLIND_NOTE
│       ├── perceived.py         Perceived
│       ├── place_in_world.py    PlaceInWorld
│       ├── screen_model.py      网格常量、地形字符、TERRAIN_MEANING、terrain_legend
│       ├── screen_state.py      ScreenState（视觉模型输出的 schema）、CURSOR_MARKS
│       ├── screen_text.py       ScreenText（dialog_text / options / cursor / option_grid / cursor_cell /
│       │                        option_details / covered + render_layout() / render_details()）
│       ├── task_scene.py        TaskScene（task 层场合词表）、TAKEOVER_SCENES
│       ├── task_observation.py  TaskObservation（Observation + scene + takeover）
│       ├── terrain_map.py       TerrainMap
│       └── vision_describe.py   VisionDescribeReq / VisionDescribeResp（world 自己的副本）
└── prompts/
    ├── __init__.py              PromptTemplate、load()
    └── perceive_screen.md       感知这条链的 prompt 素材
```

`world/__init__.py` 的 `__all__` 有 36 个名字；`PyBoyWorld` / `parse_screen` / `read_facing` / `read_passable` / `read_screen_tiles` / `read_terrain` / `classify_scene` / `at_start` 走 `_LAZY` 表懒加载（`pyboy_world` 拽着 `pyboy`），其余（`interface/` 的协议与数据形状）立即加载。

## 三、WorldPort 契约

`world/interface/world_port.py`，`@runtime_checkable` 的 `Protocol`，**8 个方法**：

| # | 方法 | 签名 | 前置条件 | 承诺 | 失败方式 |
|---|---|---|---|---|---|
| 1 | `reset` | `(*, task_id: str, goal: str, success_criteria: str, max_steps: int, initial_state_hint: str = "") -> None` | `max_steps > 0` | 按任务重置到初始状态，**不感知**——第一帧由调用方另调 `perceive_once()` / `perceive_task()` | 实现里 `assert max_steps > 0`；`state_path` 缺失在构造期就 `FileNotFoundError` |
| 2 | `all_actions` | `() -> list[str]` | 无 | 非空，且整个 episode 内不变 | 不失败 |
| 3 | `step` | `(segments: list[tuple[str, int]], *, settle: bool = True) -> None` | 每一段的按键都在 `all_actions()` 中；当前 episode 未结束 | 按序执行按键段，推进世界，**不感知** | 按键不在 `ALL_BUTTONS` 是调用方 bug，assert 拦下；实现另断言"已 `reset()`""窗口没关" |
| 4 | `perceive_once` | `() -> Perceived` | 已 `reset()` | episode 层视觉档：返回这次真调用产生的新观测（observation 非空） | 解析不出 `ScreenState` 时抛 `PerceptionAttemptFailed`（附这次的账）；其余异常就地收编成它 |
| 4′ | `perceive_task` | `() -> TaskPerceived` | 已 `reset()` | task 层：只读内存与屏幕缓冲，`TaskObservation` 带场合、`perceived=False` | 不失败 |
| 5 | `save_state` | `() -> bytes` | 无 | 模拟器完整状态（CPU / 内存 / 画面）的字节串，非空；**不推进世界** | 不失败 |
| 6 | `load_state` | `(data: bytes) -> None` | `data` 是 `save_state` 的产物 | 恢复到导出那一刻；**读档后不 tick**（09-25 实测读档即恢复画面与内存，多 tick 一帧内存就偏离） | 数据非法时 PyBoy 原样抛出 |

两个要点：**裸字段**——`reset` 收 `Task` 拆开后的五个原始值、`step` 收 `Action.sequence` 拆开的 `(按键名, 连按次数)` 列表，world 不依赖 brain 的类型。
**`settle` 只改调用方什么时候拿到控制权**，不改按键本身的效果：`True` 等"按下去之后自己走完"的过程（换图淡入淡出 / 战斗开场 / 对话逐字打出 / 菜单弹出）走完；`False` 按完即返回，链中间的键用这一档，代价是可能抄到过场的中间帧。
`perceive_once` **只问一次、不重试**——重试循环与预算归调用方 `mcpclient/game_tools.py::GameTools.perceive_with_retry`。

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

`OVERLAY_ACTIONS`（`facts.py`，动作掩码**只看 overlay**）：`NONE` → `("up", "down", "left", "right", "a", "start")`；`DIALOG` → `("a",)`；`CHOICE` → `("up", "down", "left", "right", "a", "b")`（取**并集**，不是交集）。
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

**其他常量**：`BLIND_NOTE`（`observation.py`，没做过视觉感知的那一帧顶上那一行）、
`CURSOR_MARKS = frozenset("▶►▸➤>")` 与 `NEEDS_OVERVIEW = (Facts.Scene.FIELD, Facts.Scene.INDOOR)`
（`screen_state.py`）、`_EXTRA_ORDER`（`facts.py`）。

## 五、数据形状

| 形状 | 谁产出 | 谁消费 | 关键字段 |
|---|---|---|---|
| `Observation` | `PyBoyWorld.perceive_once()` | harness（`EpisodeRunState`）、`mcpclient/game_tools.py`、trace 渲染、`schemas/harness/communication/**` | `step`（占位 0，由 Harness 盖章）、`place: PlaceInWorld \| None`、`status`、`facts: Facts`、`done`、`perceived`；方法 `stall_key()` / `render(indent="  ")` |
| `TaskObservation` / `TaskPerceived` | `PyBoyWorld.perceive_task()`（`_ram_observe`） | task 层：`GameTools.perceive_task` → `FromHarnessToGameToolPerceiveTaskResp`、`TaskState`、决策 / 反思 / 掩码 / 执行的信封、`sense_frame` 账（正文带 `scene`）、ActMemory 的前后帧（`scene` 字段） | `Observation` 的全部字段 + `scene: TaskScene`（场合，必有）+ `takeover: TakeoverView \| None`（接管场合给视图）。与 episode 层的 `Observation` 是两种观测，`scene` 与 `Facts.Scene` 只是重名 |
| `TaskScene` / `TAKEOVER_SCENES` | `scene.classify_scene()` | task 层、读屏测评 | 常规 8 类 + 接管 8 类，见 `docs/perceive/spec.md` 第三节 |
| `Facts` | `PyBoyWorld` 拼装 | harness 交互判定、`direct/prompts`、记忆检索 query | 具名 `scene`/`overlay`/`where`/`facing`/`neighbors`/`landmarks`/`dialog_text`/`options`/`cursor`/`overview`/`walk_map`/`map_id`；`extra="allow"` 接住视觉模型按 scene 自由给的字段；`scene_value` / `overlay_value` / `exclude(keys)` / `items()` / `stall_key_part()` / `render()` |
| `Facts.Scene` | 视觉模型（经 `ScreenState`） | 掩码与 prompt | `FIELD` `INDOOR` `BATTLE` `MENU` `SHOP` `TRANSITION` |
| `Facts.Overlay` | 视觉模型 | `OVERLAY_ACTIONS` 的键 | `NONE` `DIALOG` `CHOICE` |
| `Facts.Landmark` | `TerrainMap.landmarks()` | harness 交互判定 | `kind`（`KIND_DOOR`/`KIND_SIGN`/`KIND_PERSON`/`KIND_ITEM`/`KIND_BOULDER`）、`map_id`、`x`、`y`；属性 `place` 现场拼 `PlaceInWorld` |
| `PlaceInWorld` | RAM 读出的坐标 | 记忆的键、交互判定 | `map_id` / `x` / `y`；`step_toward(facing)`、属性 `key` = `"{map_id}:{x}:{y}"`、`render()` |
| `ActionSpace` | `compute_action_space()` / `mcpclient/game_tools.py::_mask()`（同一条场合规则：`scripts/catalog.SCENE_SCRIPTS`） | brain（`ChooseOnceReq`） | `mask` / `entries: list[ActionEntry]` / `names` / `descriptions` / `note` / `map_note`（接管场合 `names` 为空、只给接管脚本）；`contains(name)` / `enabled(name)` / `entry(name)` |
| `ActionEntry` / `ScriptParam` | `scripts/catalog.py`（常规脚本）、`scripts/takeover/` 各场合文件（接管脚本） | tool 层：动作空间、prompt 的脚本签名与说明、转成 brain 的 `ScriptSignature` | `kind`（`key` / `script`）/ `name` / `params`（`name` / `type`∈{str,int} / `description` / `default`，None = 必填）/ `description`；`signature()` 写成 `buy_item(item: str, count: int)` |
| `TakeoverView` | `scripts.takeover.takeover_view()`（`_ram_observe` 里） | `TaskObservation.takeover` → 接管场合的决策 prompt、`sense_frame` 账 | `ShopItemsView`（`items` 名字与价格、`money`、`bag`）/ `NamingView`（`target` 屏幕标题、`typed` 已输入）/ `BattleMenuView`（`mine` 在场那只带招式与剩余 PP、`foe`、`trainer`、`party`、`bag`）/ `FaintSwitchView`（`party`）/ `BagView`（`bag`、`party`）/ `PartyView`（`party`）/ `PcView`（`items` PC 道具、`bag`、`box` 当前箱、`box_number`、`party`）/ `LearnMoveView`（`pokemon`、`new_move`、`moves`）；队员是 `MonEntry`（昵称、等级、HP、状态、是否在场、招式）；`render()` 给 prompt 几行 |
| `Perceived` | `PyBoyWorld.perceive_once()` | `GameTools.perceive_with_retry()` | `observation` / `calls: list[dict[str, str]]` / `frame_png`（base64 PNG）/ `ram: RamReadout` |
| `RamReadout` | `readout.read_readout()` | 经 tool 层写进 `sense_frame` 账的 `ram`；**不进 agent 输入**，测评读它 | `in_battle` / `covered` / `text_source`（`decode`/`vlm`/`none`，这一帧文字实际来自哪）/ `would_be`（W4 下会来自哪）/ `menu: MenuVars` / `money` / `bag: [BagItem]` / `party: [PartyMon]` / `battle: BattleStatus \| None` / `decoded: DecodedText \| None`（legacy 档额外存解码结果，供逐帧对比） |
| `BattleStatus` | `battle_status.read_battle_status()`（不在战斗时 `None`） | `Facts` 的额外字段（`facts_fields()`）、`RamReadout.battle` | `mine` / `foe: Combatant`（`name` 取 RAM 昵称字段、`level`、`hp`、`max_hp`、`status`） |
| `ScreenState` | `parse_screen()`（视觉模型的文本） | 只有 `pyboy_world.py`——不离开 world | `scene` / `overlay` / `overview` / `dialog_text` / `options` / `option_lines` / `cursor` / `fields: dict[str, str]` |
| `TerrainMap` | `ram.read_terrain()` | `PyBoyWorld` 拼 `Facts` | `cells`（9 行 × 10 字符，构造时校验形状与字符集）/ `map_id` / `player_x` / `player_y` / `facing` / `ambiguous_cells`；`at()` / `neighbors()` / `render()` / `landmarks()` / `place()` / `render_neighbors()` |
| `VisionDescribeReq` / `VisionDescribeResp` | `PyBoyWorld` 构造请求 | `VisionProvider.describe()` | Req：`images: list[str]`（base64 PNG，`min_length=1`）+ `prompt`；Resp：`text` + `input_tokens` / `output_tokens` / `cached_tokens` / `reasoning_tokens` |
| `Memory`（Protocol） | —— | `ram.py` 的四个读函数 | `__getitem__(addr: int \| slice)`，只要能按地址取字节，不必是真 PyBoy |

`VisionDescribeReq` / `VisionDescribeResp` 是 **world 自己的一份副本**（`vision_describe.py`），
与 `brain/schemas/vision.py` 的两份**字段同构是刻意的**：world 不 import brain，
同构靠 tool 层这一座桥守。

## 六、感知链路

```
PyBoy 屏幕 → PNG 字节（_frame_png）→ base64 → VisionDescribeReq
           → VisionProvider.describe() → text → parse_screen() → ScreenState
           → 与 ram.read_terrain() 的地形拼装 → Facts + Observation → Perceived
```

**两个入口，两层各用一个**。harness 只在两层 perceive 的 `sense` 单元取帧：task 层每圈走 `perceive_task()`，
episode 层每圈走 `perceive_once()`（带 VLM）。**RAM 档也读文字**：`screen_text.read_screen_text()` 给出对话、选项、光标、
选项排布（进 `Facts` 的额外字段 `option_layout`，告诉决策"几行几列、光标在哪、方向键怎么走"），
并据此推 `overlay`（有光标 = CHOICE，有对话 = DIALOG，否则 NONE），`wIsInBattle` 非零时 `Facts.scene=battle`。
RAM 档产出 `TaskObservation`：另带场合 `scene`（`scene.classify_scene`，读屏幕缓冲 + `wIsInBattle` / `wListPointer` / `wCurMapTileset`）；
画面字段二选一——屏上有字只给 `Facts.screen`，没字（走路）只给 `Facts.walk_map`。
完整档里 options / cursor 也以 RAM 读数覆盖视觉模型的抄写。

| 档 | 调模型 | 读什么 | `perceived` | `calls` |
|---|---|---|---|---|
| `perceive_once()` | 是，一次 | 内存 + 视觉 | `True` | 一条账 |
| `perceive_task()` | 否 | 只有内存：坐标、朝向、地标、通行图（屏上没字时）、地图编号 + 屏幕文字（对话 / 选项 / 光标 / 排布 / overlay / 战斗）+ 场合 | `False`——概况等视觉字段**不是空的，是没读过** | 没有（`TaskPerceived` 不带账） |

两档都截帧：`frame_png` 照截照传——"帧的可得性与有没有人看过它无关"。

**读数来源与两层分工（0926 定，取代 W4）**：

| 来源 | 给什么 | 可靠性 |
|---|---|---|
| 游戏变量 | 坐标 / 地图 / 朝向 / 通行图 / 地标、在不在战斗、战斗双方名字 / 等级 / HP / 状态（`my_*` / `foe_*`） | 确定 |
| 屏幕字符缓冲 | 切好的对话 / 选项 / 光标 / 排布 / `×` `¥` 附注（尽力）+ 整屏原样 `Facts.screen`（`screen_text.render_screen`） | 字符确定，切分尽力 |
| 视觉模型 | `scene`、`overview`、场合字段；episode 层的对话 / 选项 / 光标 | 会看错 |

- **task 层（`perceive_task()`）**：不调视觉。文字字段来自解码，另给整屏原样；解码切不出的界面（队伍列表、
  数量框、起名键盘……）由模型自己读 `screen`（`decide_action.md` 写明"字段对不上时以 `屏幕` 为准"）。
- **episode 层**：调一次视觉，文字字段以视觉为准（解码不再覆盖视觉的选项 / 光标）；也给整屏原样，
  `decompose.md` 写明"字面内容听 `屏幕`，图形和场面听视觉"。
- **整屏渲染**：一个图块一个字符；边框 `┌─┐│└┘`（含战斗 HUD 框线 0x6F / 0x76–0x78）、等级 `:L`、
  血条 `HP:[██████]`（每格 8 像素按填充渲染）、`ID` / `No.` 只在战斗外渲染，其余非文字图块 `·`。
  `:L` / `HP:` 一个图块占两三个字符，所在行后面的列会右移。整屏既没字也没边框（走路、过场）时给空串。
  记忆快照存 `screen`，历史渲染（`ActMemory._render_obs`）也保留它（只去掉 `walk_map`），judge / verify 看得到。
- **叠加层**（`pyboy_world._overlay_of`）：屏幕上有 `▶` 或数量框（`×` 紧跟两位数字）→ CHOICE；
  严格的对话帧（`ScreenText.strict_dialog`：底部对话框有字、没有 `▶`、没有数量框、对话框外没有别的框）→ DIALOG；
  其余 NONE。看档路径上视觉说 DIALOG 还要解码认得是严格对话帧，否则按解码推（`_checked_overlay`）。
- **掩码**：DIALOG 只给 `a`；NONE 与 CHOICE 都给 `上下左右 + a + b + start`（`_OPEN_KEYS`）——
  叠加层判错的代价只是多几个当帧无效的键。
- **测评**：`RamReadout.decoded` 每帧都记（两层），机械判据只读它；`covered` 只做统计。

**prompt**：`PyBoyWorld.__init__` 用 `world/prompts/__init__.py::load("perceive_screen")` 读
`prompts/perceive_screen.md`，`perceive_once()` 里以
`render(known_map=terrain.render(), terrain_legend=terrain_legend())` 填两个 `$` 占位符。

**账的形状**（`dict[str, str]`，值一律 `str`）：成功给 `input_tokens` / `output_tokens` /
`cached_tokens` / `reasoning_tokens` / `ok`（`"true"`/`"false"`）/ `raw` / `prompt`；
失败给 `ok="false"` / `raw=""` / `prompt` / `error`（`"{类型名}: {消息}"` 前缀），
由 `PerceptionAttemptFailed(call)` 带出，读方是它的 `.call` 属性。

**跨步骤的常量不在 world**：重试预算 `PERCEPTION_MAX_RETRIES = 3` 与固定退避
`MODEL_RETRY_BACKOFF_SECONDS = 0.5` 在 `pokemon_agent/config.py`，循环在
`GameTools.perceive_with_retry()`——world 只抛一次性的 `PerceptionAttemptFailed`。

两条实现规则：视觉模型报 `overlay=DIALOG` 却一个字都没抄出来时**降级成 `NONE`**
（免得用假对话算出一组按不出效果的掩码）；task 层的状态行由 `_ram_status()` 生成，
只写它真读过的东西，不编"你在野外"这类场景词。

## 七、接管脚本（`scripts/takeover/`）

接管场合里 JEV 不按键，选一条带参数的接管脚本；world 执行到底。它与常规脚本是**同一种动作**
（`ActionEntry`，`kind="script"`，经 `GameTools.execute` 的脚本通道执行，记 `act_call` script 形），
差别在可用场合和脚本选择的规则，执行现场相同。**对外名 = 场合前缀 + 文件内短名**（`shop_quit` = `shop` + `quit`），
前缀表 `takeover.PREFIX` 是唯一规则。每个场合一个文件，每条只写**前提校验 + 执行 + 收尾**，
这些脚本通过 `definitions.run_definition` 执行显式声明的 `menu_policy`：

1. **认场合、找脚本、核参数类型**：场合不是接管场合或本场合没有这条 → `rejected / unknown_script`；缺参数、类型不对 → `rejected / bad_args`（一个键都不按）。
2. **回初态**：等画面稳定（每 `POLL_FRAMES` 帧读一次、连续 `STABLE_POLLS` 次相同，忽略闪烁的 `▼`）→ `at_start` 真则进 3；场合已变 → `left_scene`；否则按 B，最多 `REWIND_LIMIT` 次（超了 `aborted / rewind_limit`）。
3. **按此刻内存校验前提**（钱、背包、商品、持有数、名字字符与长度、招式与 PP、队员）→ 不满足 `rejected`，原因码见 `ScriptReason`（商店与起名：`unknown_item` `not_enough_money` `bag_full` `quantity_out_of_range` `not_in_bag` `key_item` `invalid_name`；战斗：`unknown_move` `no_pp` `unknown_pokemon` `pokemon_fainted` `already_active` `target_required` `cannot_use`；通用：`unknown_script` `bad_args` `rewind_limit` `step_timeout` `unexpected_screen`）。
4. **执行**：每一步按键后等稳定、核对期望（`wait_for` 只在没有光标、没有数量框时按 A 推进文字）；没出现期望 → 回初态、`aborted`。
5. **收尾**：回初态（离开场合的脚本不回），`done` 带一行 `summary`（如 `钱 3000→2000，POKé BALL +5`）。

执行直接返回统一的 `ScriptResult`：`ok` = `done`；`code` = `ok` / 原因码 / 结局。
菜单脚本的 `data` 带 `scene` / `status` / `reason` / `summary` / `steps`；逐步明细由脚本的 `record_steps` 配置启用。
所有脚本只经同一个 `WorldConsole` 协议碰模拟器。`ScriptRun` 不默认启用三种中断；地图操作脚本选择 `field_policy`，菜单操作脚本声明严格等待、初态恢复和收尾。开始菜单导航与回血确认同样使用这个执行器，其步骤明确不启用选项中断。

| 场合 | 接管脚本（对外名） | 视图 |
|---|---|---|
| `shop_items` | `shop_quit()`；买卖走带白名单与终态对账的常规脚本 `buy_item(item, count)` / `sell_item(item, count)`，它们经 `console.run_script` 组合调用内部的 `shop_buy` / `shop_sell`（这两条不单独给模型） | `ShopItemsView` |
| `naming` | `naming_enter_name(name)`（只收大写字母，长度 ≤ 7，`NICKNAME?` ≤ 10） | `NamingView` |
| `battle_menu` | `battle_fight(move)`、`battle_switch(pokemon)`、`battle_use_item(item, pokemon="")`、`battle_run()` | `BattleMenuView` |
| `faint_switch` | `faint_send_out(pokemon)` | `FaintSwitchView` |
| `bag` | `bag_use(item, pokemon="")`、`bag_toss(item, quantity)`、`bag_close()` | `BagView` |
| `party` | `party_switch(a, b)`、`party_field_move(pokemon, move)`、`party_stats(pokemon)`、`party_close()` | `PartyView` |
| `pc` | `pc_withdraw_item` / `pc_deposit_item` / `pc_toss_item(item, quantity)`、`pc_withdraw_pokemon` / `pc_deposit_pokemon(pokemon)`、`pc_change_box(n)`、`pc_log_off()` | `PcView` |
| `learn_move` | `learn_forget(move)`、`learn_skip()` | `LearnMoveView` |

**战斗接管脚本的收尾是自动推进战斗文字**（`ScriptRun.advance`）：只在屏上出现 `▼`（游戏在等按键）、或画面静止满
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

**谁能碰实现：只有 tool 层**。`mcpclient/game_tools.py:37`（`OVERLAY_ACTIONS` / `ActionSpace` /
`Facts` / `Observation` / `WorldPort`）、`:44`（`world.errors.PerceptionAttemptFailed`）、
`:137`（`PyBoyWorld`，在 `GameTools.build()` 函数体内）、`brain/vision_factory.py:36`
（`VisionProvider`）、`direct/brain_tool.py:91`（`DIRECTION_KEYS` / `INTERACT_KEY`）、
`direct/prompts/decide_action.py:32-33`（`terrain_legend` / `Facts`）、
`direct/trace/render.py:86`（`Observation`）。非 tool 侧只许 import `pokemon_agent.world`
与 `pokemon_agent.world.interface*`（数据形状）。

**核对脚本**：`python scripts/check_world_self_contained.py`（退出码 0 = 全过），查三类：

- **A〔出边为零〕**：`world/` 包内**没有任何文件** import `pokemon_agent` 的其余部分
  （相对 import 先按 PEP 328 解析成绝对名再判）。
- **B〔实现面只在 `tools/`〕**：`world/` 与 `tools/` 之外的 `.py` 只许 import
  `pokemon_agent.world` 与 `pokemon_agent.world.interface*`；白名单式——新增一个
  `world/xxx.py` 默认就是"实现面"，要放行得改 `ALLOWED_OUTSIDE_TOOLS`。
- **C〔装配点零 import〕**：`build.py` 一个字都不许 import `pokemon_agent.world`
  （`GameTools.build()` / `build_vision_provider()` 全在 tool 层）。

末尾另打印一份**账本**（不算失败）：非 tool 侧对 world 数据形状的 import 点，当前 **12 处**
（`harness/episode` 4、`schemas/harness/communication` 8）。`AGENTS.md` 第十二节第 4 条登记的
14 处是旧计数，以脚本输出为准。脚本只看 import 语句，不看 docstring 散文。

## 九、当前状态与已知缺口

**已成立**：A/B/C 三类约束全过（脚本实测）；两层读数分工与整屏渲染已落地（0926，W4 撤销）；`WorldPort` 由 `PyBoyWorld` 唯一实现，
方法签名与第三节的契约表一致。

**已知缺口**（均不影响运行，但读代码时会被误导）：

- `pyboy_world.py` 模块 docstring 说"感知按帧哈希缓存……重复 `observe()` 不调模型"，
  但 `PyBoyWorld` **没有 `observe()` 方法、也没有任何缓存字段**——重复调 `perceive_once()`
  每次都会真问一遍模型。这段缓存叙述是陈旧的。
- `_Task` 的 docstring 写"`reset()`/`set_task()` 收到的裸字段"，但 `WorldPort` 与
  `PyBoyWorld` **都没有 `set_task()`**。
- `evolve()` 的 docstring 自称"仍是 `WorldPort` 契约的一部分"，但 `world_port.py`
  只声明了上面 8 个方法，**没有声明 `evolve`**；它当前的唯一调用方是
  `mcpclient/game_tools.py::GameTools.evolve`。
- `TerrainMap.cells` 的字段说明引用
  `pokemon_agent.schemas.world.domain.screen_model.MAP_CHARS`——该路径已无对应文件
  （`pokemon_agent/schemas/world/` 只剩空的 `communication/`、`domain/` 两个目录），
  常量实际住在 `world/interface/domain/screen_model.py`。
- `facts.py` 顶层那段导入顺序说明、`terrain_map.py` 模块 docstring 引用的
  `schemas/world/domain/observation_from_world.py` 同样已不存在；代码里"运行时才 import"
  的写法仍然保留着。
