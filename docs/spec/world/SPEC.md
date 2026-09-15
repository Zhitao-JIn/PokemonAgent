# world —— 模块规格

> 最后更新：2026-09-15 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

world 是 `WorldPort` 的唯一实现：把 PyBoy 模拟器与视觉模型粘成"一个可推进、可观测的世界"，
外加这个世界自己的语义常量（按哪个键、往哪个方向、哪个键算互动、地形字符什么意思）。

一帧画面变成 `Observation` 要经过两条来源，各管一段，互不替代（`world/pyboy_world.py` 的模块
docstring）：`world/ram.py` 给出坐标、地图编号、朝向、地形通行图、门与招牌的位置——确定，不会
读错；视觉模型给出场景类别、对话框文字、屏幕上有什么——会读错，所以要记账。

边界四条：

- **出边为零**：`world/` 包内不 import `pokemon_agent` 的其余部分（第七节有可执行核对）。
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
├── interface/
│   ├── __init__.py              统一出口（协议 + 数据形状 + 常量）
│   ├── world_port.py            WorldPort 契约（4 个方法）
│   ├── vision_provider.py       VisionProvider 协议（describe）
│   ├── memory.py                Memory 协议（按地址取字节）
│   └── domain/
│       ├── __init__.py          统一出口，__all__ 27 个名字
│       ├── action_semantics.py  BUTTON_FACING / FACING_STEP / DIRECTION_KEYS / INTERACT_KEY
│       ├── action_space.py      ActionSpace
│       ├── facts.py             Facts（内部类 Scene/Overlay/Landmark）+ OVERLAY_ACTIONS
│       ├── observation.py       Observation、BLIND_NOTE
│       ├── perceived.py         Perceived
│       ├── place_in_world.py    PlaceInWorld
│       ├── screen_model.py      网格常量、地形字符、TERRAIN_MEANING、terrain_legend
│       ├── screen_state.py      ScreenState（视觉模型输出的 schema）、CURSOR_MARKS
│       ├── terrain_map.py       TerrainMap
│       └── vision_describe.py   VisionDescribeReq / VisionDescribeResp（world 自己的副本）
└── prompts/
    ├── __init__.py              PromptTemplate、load()
    └── perceive_screen.md       感知这条链的 prompt 素材
```

`world/__init__.py` 的 `__all__` 有 36 个名字；`PyBoyWorld` / `parse_screen` / `read_facing` / `read_passable` / `read_screen_tiles` / `read_terrain` 走 `_LAZY` 表懒加载（`pyboy_world` 拽着 `pyboy`），其余（`interface/` 的协议与数据形状）立即加载。

## 三、WorldPort 契约

`world/interface/world_port.py`，`@runtime_checkable` 的 `Protocol`，**4 个方法**：

| # | 方法 | 签名 | 前置条件 | 承诺 | 失败方式 |
|---|---|---|---|---|---|
| 1 | `reset` | `(*, task_id: str, goal: str, success_criteria: str, max_steps: int, initial_state_hint: str = "") -> None` | `max_steps > 0` | 按任务重置到初始状态，**不感知**——第一帧由调用方另调 `perceive_once()` | 实现里 `assert max_steps > 0`；`state_path` 缺失在构造期就 `FileNotFoundError` |
| 2 | `all_actions` | `() -> list[str]` | 无 | 非空，且整个 episode 内不变 | 不失败 |
| 3 | `step` | `(segments: list[tuple[str, int]], *, settle: bool = True) -> None` | 每一段的按键都在 `all_actions()` 中；当前 episode 未结束 | 按序执行按键段，推进世界，**不感知** | 按键不在 `ALL_BUTTONS` 是调用方 bug，assert 拦下；实现另断言"已 `reset()`""窗口没关" |
| 4 | `perceive_once` | `(*, ram_only: bool = False) -> Perceived` | 已 `reset()` | 返回这次真调用产生的新观测（observation 非空） | 解析不出 `ScreenState` 时抛 `PerceptionAttemptFailed`（附这次的账）；其余异常就地收编成它 |

两个要点：**裸字段**——`reset` 收 `Task` 拆开后的五个原始值、`step` 收 `Action.sequence` 拆开的 `(按键名, 连按次数)` 列表，world 不依赖 brain 的类型。
**`settle` 只改调用方什么时候拿到控制权**，不改按键本身的效果：`True` 等"按下去之后自己走完"的过程（换图淡入淡出 / 战斗开场 / 对话逐字打出 / 菜单弹出）走完；`False` 按完即返回，链中间的键用这一档，代价是可能抄到过场的中间帧。
`perceive_once` **只问一次、不重试**——重试循环与预算归调用方 `tools/game_tools.py::GameTools.perceive_with_retry`。

实现类 `PyBoyWorld` 另有两个不在 `WorldPort` 里的方法：`stop()` 与 `evolve(frames)`
（`assert frames >= 0`）——见第八节。

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
| `Observation` | `PyBoyWorld.perceive_once()` | harness（`EpisodeRunState`）、`tools/game_tools.py`、trace 渲染、`schemas/harness/communication/**` | `step`（占位 0，由 Harness 盖章）、`place: PlaceInWorld \| None`、`status`、`facts: Facts`、`done`、`perceived`；方法 `stall_key()` / `render(indent="  ")` |
| `Facts` | `PyBoyWorld` 拼装 | harness 交互判定、`tools/prompts`、记忆检索 query | 具名 `scene`/`overlay`/`where`/`facing`/`neighbors`/`landmarks`/`dialog_text`/`options`/`cursor`/`overview`/`walk_map`/`map_id`；`extra="allow"` 接住视觉模型按 scene 自由给的字段；`scene_value` / `overlay_value` / `exclude(keys)` / `items()` / `stall_key_part()` / `render()` |
| `Facts.Scene` | 视觉模型（经 `ScreenState`） | 掩码与 prompt | `FIELD` `INDOOR` `BATTLE` `MENU` `SHOP` `TRANSITION` |
| `Facts.Overlay` | 视觉模型 | `OVERLAY_ACTIONS` 的键 | `NONE` `DIALOG` `CHOICE` |
| `Facts.Landmark` | `TerrainMap.landmarks()` | harness 交互判定 | `kind`（`KIND_DOOR`/`KIND_SIGN`/`KIND_PERSON`/`KIND_ITEM`/`KIND_BOULDER`）、`map_id`、`x`、`y`；属性 `place` 现场拼 `PlaceInWorld` |
| `PlaceInWorld` | RAM 读出的坐标 | 记忆的键、交互判定 | `map_id` / `x` / `y`；`step_toward(facing)`、属性 `key` = `"{map_id}:{x}:{y}"`、`render()` |
| `ActionSpace` | `tools/game_tools.py::_mask()`（world 只给 `OVERLAY_ACTIONS` 与 `all_actions()`） | brain（`ChooseOnceReq`） | `names` / `descriptions` / `note` / `map_note`；`contains(name)` |
| `Perceived` | `PyBoyWorld.perceive_once()` | `GameTools.perceive_with_retry()` | `observation` / `calls: list[dict[str, str]]` / `frame_png`（base64 PNG） |
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

**两档，由 `ram_only` 选**（对照 `harness/episode/press/perceive_after_action.py`：
链中间的键 `ram_only=True`，链尾那一键走完整档）：

| 档 | 调模型 | 读什么 | `perceived` | `calls` |
|---|---|---|---|---|
| `ram_only=False`（缺省） | 是，一次 | 内存 + 视觉 | `True` | 一条账 |
| `ram_only=True` | 否 | 只有内存：坐标、朝向、地标、通行图、地图编号 | `False`——场景/对话/概况**不是空的，是没读过** | 空列表（不是 `None`） |

两档都截帧：`frame_png` 照截照传——"帧的可得性与有没有人看过它无关"。

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
（免得用假对话算出一组按不出效果的掩码）；`ram_only` 档的状态行由 `_ram_status()` 生成，
只写它真读过的东西，不编"你在野外"这类场景词。

## 七、依赖边界与自包含核对

**出边为零**：`world/` 内唯一的绝对 import 是 `from pokemon_agent.world import …`
（`pyboy_world.py:26`），其余全是相对 import。⇒ 整个 `world/` 拷进另一个项目仍能跑。

**谁能碰实现：只有 tool 层**。`tools/game_tools.py:37`（`OVERLAY_ACTIONS` / `ActionSpace` /
`Facts` / `Observation` / `WorldPort`）、`:44`（`world.errors.PerceptionAttemptFailed`）、
`:137`（`PyBoyWorld`，在 `GameTools.build()` 函数体内）、`tools/vision_factory.py:36`
（`VisionProvider`）、`tools/brain_tool.py:91`（`DIRECTION_KEYS` / `INTERACT_KEY`）、
`tools/prompts/decide_action.py:32-33`（`terrain_legend` / `Facts`）、
`tools/trace/render.py:86`（`Observation`）。非 tool 侧只许 import `pokemon_agent.world`
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

## 八、当前状态与已知缺口

**已成立**：A/B/C 三类约束全过（脚本实测）；`WorldPort` 由 `PyBoyWorld` 唯一实现，
四个方法签名与第三节的契约表一致。

**已知缺口**（均不影响运行，但读代码时会被误导）：

- `pyboy_world.py` 模块 docstring 说"感知按帧哈希缓存……重复 `observe()` 不调模型"，
  但 `PyBoyWorld` **没有 `observe()` 方法、也没有任何缓存字段**——重复调 `perceive_once()`
  每次都会真问一遍模型。这段缓存叙述是陈旧的。
- `_Task` 的 docstring 写"`reset()`/`set_task()` 收到的裸字段"，但 `WorldPort` 与
  `PyBoyWorld` **都没有 `set_task()`**。
- `evolve()` 的 docstring 自称"仍是 `WorldPort` 契约的一部分"，但 `world_port.py`
  只声明了 4 个方法，**没有声明 `evolve`**；它当前的唯一调用方是
  `tools/game_tools.py::GameTools.evolve`。
- `TerrainMap.cells` 的字段说明引用
  `pokemon_agent.schemas.world.domain.screen_model.MAP_CHARS`——该路径已无对应文件
  （`pokemon_agent/schemas/world/` 只剩空的 `communication/`、`domain/` 两个目录），
  常量实际住在 `world/interface/domain/screen_model.py`。
- `facts.py` 顶层那段导入顺序说明、`terrain_map.py` 模块 docstring 引用的
  `schemas/world/domain/observation_from_world.py` 同样已不存在；代码里"运行时才 import"
  的写法仍然保留着。
