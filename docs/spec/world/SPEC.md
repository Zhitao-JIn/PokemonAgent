# `world` 模块技术规格

覆盖文件：
- `pokemon_agent/world/pyboy_world.py`
- `pokemon_agent/world/ram.py`
- `pokemon_agent/interfaces/world.py`（`WorldPort` 协议）
- `pokemon_agent/interfaces/vision.py`（`VisionProvider` 协议）

---

## 1. 模块定位

`world` 是整个 agent 系统里**真实世界的唯一实现**。它把两样东西粘在一起：

- **PyBoy**：Game Boy 模拟器，负责实际推进游戏、读内存、出画面。
- **视觉模型（`VisionProvider`）**：负责把一帧画面翻译成结构化的 `ScreenState`（场景类型、对话框文字、选项、总览描述等）。

`PyBoyWorld` 是 `WorldPort` 协议目前唯一的实现。`WorldPort` 本身定义在 `interfaces/world.py`，是"harness 底下的那一层"——**大脑（决策 LLM）看不到这个文件**，它只通过 harness 间接消费 `Observation`。

### 1.1 和 `tools/game_tools.py` 的边界

项目里有两层与"世界"打交道的代码：

| 层 | 职责 | 是否感知 |
|---|---|---|
| `WorldPort` / `PyBoyWorld`（本模块） | 世界本身能做什么：`reset`/`observe`/`inspect`/`step`/`all_actions` | **是**，所有调 VLM、读内存、组装 `Observation.facts` 的逻辑都在这里 |
| `GameToolPort` / `GameTools`（`tools/game_tools.py`） | Harness 能拿世界做什么，即暴露给"决策"链路的工具接口 | **否**，`GameTools` 只是用 `WorldPort` 去实现 `GameToolPort`，纯粹转发调用，不掺杂任何感知/解析逻辑 |

`interfaces/world.py` 的 docstring 把这条分界讲得很直接：

> `GameToolPort` 是"Harness 能拿世界做什么"，`WorldPort` 是"世界本身能做什么"，两者职责不同且变化速度不同。`GameTools` 用 `WorldPort` 实现 `GameToolPort`。当前唯一的实现是 `PyBoyWorld`，换模拟器时 **`GameToolPort` 和大脑一行都不用改**——这就是分层的收益。

也就是说，只要 `PyBoyWorld` 遵守 `WorldPort` 协议，未来换一个模拟器（甚至换成非 PyBoy 的实现）时，`tools/game_tools.py` 和大脑侧代码完全不需要改动。**感知（VLM 调用、地形读取、对话框误判修正等）全部封闭在 `world` 内部**，不会泄漏到 tools 层或大脑侧。

另外一条明确写在协议里的边界：**动作掩码（masking）不是 world 的职责**，是 harness 的策略。`world` 只回答"全部动作是什么"（`all_actions()`）和"执行这个动作会怎样"（`step()`），至于当前状态下哪些动作可用，是 harness 结合 `Observation.facts["overlay"]` 查 `OVERLAY_ACTIONS` 表来决定的。

---

## 2. `ram.py`：`read_terrain` —— 从模拟器内存读地形

### 2.1 为什么地形来自内存，不来自视觉模型（"骨架"论证的完整版）

模块头部的中文注释记录了完整的实测历史与论证：

**试验过程**：视觉模型识别地形试了三轮（方向字段 → 通行性二值 → 语义符号），每轮换的都是"问法"，但答案质量没变——墙被认成门、窗户被认成人。**瓶颈不在问法，在通道本身**：从 160x144 像素里做 90 次格子级分类，本来就不是 VLM 擅长的事。

**关键洞察**：这个判断（某格能不能走）游戏引擎自己每一步都在做。`CheckTilePassable`（红版原版反汇编里的例程）的全部逻辑是：

```
取目标格的 tile id，去 wTilesetCollisionPtr 指向的表里线性查找，
命中 = 能走，查到 $FF = 撞墙。
```

`read_terrain` / `read_passable` 照抄这一段。**没有阈值、没有识别、没有概率**，几何这一维直接是 100% 精确。

**分工的完整论证**（按"错了会怎样"划线，不是按"谁能做"划线）：

```
地形 / 门 / 招牌 / 人 / 草丛 / 坐标 / 地图编号   ← 这个模块（模拟器内存，精确）
这看起来是什么地方 / 对话文本 / 战斗数值 / 名字   ← 视觉模型（看图，会错）
```

- **线上面**（地形骨架）：错一个就是 agent 撞墙、走错门、跟空气说话——每一步都在用，错误会**沿着轨迹放大**。所以必须精确，而内存里恰好就有精确答案。
- **线下面**（语义描述）：错了只是"描述得不准"，把民宅说成宝可梦中心，大脑顶多多走一趟，不会放大成行动错误。而且这类判断（"这里看起来是个小镇"）**没有别的来源**——只有看图才给得出，那正是视觉模型擅长的。

结论：视觉模型现在的角色是**给这张精确的地图配一段人话**，不是提供事实本身。

### 2.2 实测验证（2026-08-19，真新镇存档）

- 20x18 通行图与画面逐格吻合：树、房子、招牌、门的位置全对。
- 唯一"四个子 tile 意见不一"的格子正好是**门**，取左下子格后与画面一致（见 2.4 `SUB_TILE`）。
- 连按 `left` 三次主角坐标不动——因为那格是树。**读出的图正确预测了撞墙。**

### 2.3 关键地址常量

| 常量 | 地址 | 含义 |
|---|---|---|
| `W_TILEMAP` | `0xC3A0` | 屏幕上 20x18 个 tile 的 id。**已经是屏幕坐标**——游戏自己维护的"当前画面"缓冲区，不需要处理 SCX/SCY 滚动，也不会截到滚动中途的半格。比直接读 PPU 背景层省掉一整类对齐问题。 |
| `SCREEN_COLS, SCREEN_ROWS` | 20, 18 | 屏幕 tile 网格尺寸 |
| `W_CUR_MAP` | `0xD35E` | 当前地图编号 |
| `W_Y_COORD, W_X_COORD` | `0xD361, 0xD362` | 主角地图坐标 |
| `W_COLLISION_PTR` | `0xD530` | 指向当前 tileset 碰撞表的指针（小端两字节） |
| `W_GRASS_TILE` | `0xD535` | 当前 tileset 里代表野草的 tile id |
| `W_NUM_WARPS` | `0xD3AE` | 门（warp）数量，后跟 N 条 `(y, x, 目标 warp, 目标地图)`。实测真新镇读出 3 条，目标 map 37/39/40（自己家/小茂家/大木研究所），坐标与画面吻合。 |
| `W_NUM_SIGNS` | `0xD4B0` | 招牌数量，后跟 N 条 `(y, x)`。实测真新镇读出 4 条，其中 `(y=5, x=11)` 换算到屏幕正是画面里那块招牌。 |
| `W_SPRITES` | `0xC100`，`SPRITE_STRIDE=16` | 精灵表。每精灵 16 字节，只用四个偏移：`+0` 图片 id（0=空槽）、`+4` 屏幕 y 像素、`+6` 屏幕 x 像素、`+9` 朝向（0下/4上/8左/C右）。0 号槽位是主角自己。实测主角 `(x=64, y=60)` 换算正好是格子 `(4,4)`，y 差的 4 像素是贴图偏移。 |
| `SUB_TILE = (0, 1)` | — | 一个 16x16 格子由 4 个 8x8 子 tile 组成，`(dc, dr)=(0,1)` 表示取**左下**子 tile 去查通行表（见 2.4）。 |

`read_passable` 的一个重要细节：**碰撞表在 bank 0（home bank），不在 `wTilesetBank`**。指针落在 `0x0000-0x3FFF` 常驻区；`wTilesetBank` 管的是 blocks/gfx 数据，不是碰撞表。作者第一版照 `wTilesetBank` 读，取到的是别的数据段的两个字节——**不报错，只是安静地给出一张错的表，导致整屏被判定成"不可通行"**。这是本模块里一个典型的"静默错误比崩溃更危险"的教训，因此 `read_passable` 加了后置断言：空集合意味着满屏都走不了，这不可能是游戏真实状态，只可能是读错了地址。

### 2.4 `SUB_TILE`：取左下子格的依据

每个 16x16 逻辑格由 4 个 8x8 子 tile 组成，`read_terrain` 需要决定用哪个子 tile 去查通行表。作者的注释明确这**是实测定出来的，不是猜的**：

- 90 个格子里只有一个四子格意见不一致——右边那栋房子的门：左上 `0x0B`、右上 `0x0C`、右下 `0x1C` 都不可通行，只有左下 `0x1B` 可通行。取左下，门就与画面一致（能进）。
- 这也符合直觉：碰撞判的是**脚下那一格**，而角色贴图的脚在格子下半部。
- 作者也坦承样本量的局限：只有一个歧义格，所以这条规则是"当前证据支持"，不是"已证明"。真正的判据是 `ambiguous_cells`（`TerrainMap` 字段）：它数出还有多少格子四个子 tile 通行性意见不一，一旦这个数涨起来，就说明这条采样规则不够用了，需要回去看游戏引擎实际怎么算。

### 2.5 `read_terrain` 的完整逻辑

```python
def read_terrain(mem: Memory) -> TerrainMap
```

步骤：

1. `read_passable(mem)` 拿到当前 tileset 的可通行 tile id 集合。
2. `read_screen_tiles(mem)` 拿到 20x18 的屏幕 tile id 矩阵。
3. 逐个 10x9 逻辑格（`GRID_ROWS x GRID_COLS`）遍历：
   - 取该格 4 个子 tile 的通行性，若不全一致则 `ambiguous` 计数 +1（对应 `TerrainMap.ambiguous_cells`）。
   - 用 `SUB_TILE` 指定的左下子 tile 判定该格：等于草地 tile 则标 `GRASS`；否则可通行标 `.`、不可通行标 `#`。
4. 读主角坐标 `(px, py)`，结合 `PLAYER_CELL`（主角在屏幕格子里的固定位置）建立地图坐标 → 屏幕格子坐标的映射函数 `place`。
5. 依次叠加招牌（`SIGN`）、门（`DOOR`）、人（`PERSON`）：
   - **叠加顺序即优先级**，后写的盖前面的：招牌 < 门 < 人。人放最后是因为"他可能站在门口"——那时"这里有个人"比"这里有扇门"更要紧（得先交互或绕开），门在他身后暂时没有意义。
   - `place()` 对越界坐标（地图上的门/招牌大多不在当前屏幕内）**静默丢弃**，因为那不是错误，只是这一帧看不到。
   - 人的位置来自精灵表，遍历槽位 1-15（0 号是主角自己，跳过），图片 id 为 0 表示空槽跳过；屏幕像素坐标换算成格子坐标 `c, r = sx//16, (sy+4)//16`。
6. 返回 `TerrainMap(cells=..., map_id=..., player_x=px, player_y=py, ambiguous_cells=ambiguous)`。

后置条件：`cells` 是 `GRID_ROWS` 行、每行 `GRID_COLS` 个字符；主角那格标 `@`（由 `TerrainMap` 自身逻辑处理，见 `PLAYER_CELL`）。

语义符号（门/招牌/人/草丛）之所以也能来自内存而非视觉识别，是因为红版把这些全存成了结构化的表：门在 warp 表里（还带着目标地图），招牌在 sign 表里，人在精灵表里，草丛的 tile id 写在 tileset 头里。所以这里读出来的每个符号都是精确的，不存在"认"这个动作——而这正是视觉模型三轮尝试都会认错的类别（墙认成门、窗户认成人）。

---

## 3. `pyboy_world.py`：`PyBoyWorld` 类

### 3.1 顶层设计取舍（类之前的模块级论证）

- **分层**：`observe()` 的契约要求交出含 `summary` 与 `facts` 的 `Observation`，而这必须调 VLM——所以感知只能在 world 里。但掩码是 harness 的策略，依赖的 `overlay`/`scene` 是感知产物；解法是**把 `scene` 与 `overlay` 放进 `Observation.facts`**，harness 读 `facts` 做掩码不算越界（`facts` 本就是 `Observation` 的公开部分）。
- **时序：同步 + 固定缓冲**，流程是"按一次键 → 推进 1 秒 →（若连按，重复）→ 推进 2 秒 → 感知"。
  - 曾用"连续 N 帧不变"判稳定，不可行：草丛、水面、NPC 走动、闪烁光标、战斗呼吸动画很多画面根本不会静止，等稳定会大面积超时。
  - 曾把模拟器放进后台线程异步跑，让模型思考时间充当天然等待；动画问题自己消失，但代价是**不可复现**（同一存档跑两次结果不同），且线程/队列/条件变量/退出唤醒的复杂度全是为了这一个好处。
  - 固定缓冲用远少的代码换到同一效果的九成，还顺带拿回了可复现性。剩下的风险（偶尔感知到动画中间帧）是概率问题不是正确性问题，可测量但不必优先解决。
- **不判断动作有没有生效**：画面本来就在动，像素比对量不出因果；动作没生效的话下一步观测会照实反映，由大脑自己纠正。
- **不判成败、不数步**：任务达成需要一次独立模型调用，world 不该认识 LLM；走了几步是循环的账，同一世界要跑不同步数上限的任务。这两件事都在 `Harness`。
- **`observe()` 必须缓存**：契约写明幂等只读，但每调一次就是一次 VLM 调用；不缓存的话动作空间计算与感知各调一次，每步感知成本翻倍。

### 3.2 构造函数参数

```python
def __init__(
    self,
    rom: str,
    vision: VisionProvider,
    *,
    state_path: str | None = None,
    prompt_name: str = "perceive_screen",
    max_perceive_retries: int = 2,
    inspect_prompt_name: str = "inspect_focus",
    watch: bool = False,
    speed: int = 1,
) -> None
```

| 参数 | 作用 |
|---|---|
| `rom` | ROM 文件路径。构造时立即检查存在性，不留到 `reset()`；文件缺失是纯粹的配置问题，越早报错离病因越近。 |
| `vision` | `VisionProvider` 实现，感知链路唯一的模型出口。 |
| `state_path` | 起始存档路径，**显式传入**，不用 PyBoy 默认的 `<rom>.state`。理由：后续会有多个命名起点（真新镇出口/一号道馆前/…），默认路径只有一个坑位，且改 ROM 文件名就对不上；用哪个存档起跑要进 manifest。若给出且文件不存在，构造时立刻抛 `FileNotFoundError`。若为 `None`，`reset()` 时从开机空转 `BOOT_FRAMES` 帧越过开机 logo。 |
| `prompt_name` | 主感知 prompt 模板名（默认 `perceive_screen`），供 `_perceive()` 用。 |
| `max_perceive_retries` | `_perceive()` 解析失败时的重试上限。前置条件 `>= 1`，构造时 `assert`。 |
| `inspect_prompt_name` | `inspect()` 用的追问 prompt 模板名（默认 `inspect_focus`）。 |
| `watch` | 是否开窗口实时观看。为 `True` 时用 `window="SDL2"`，否则 `window="null"`（无头）。也决定 `set_emulation_speed` 是否受 `speed` 控制还是恒为 0（无头不限速）。 |
| `speed` | `watch=True` 时的模拟器播放速度。`watch=False` 时该参数不生效（速度设为 0，即不限速全速跑）。 |

**存档载入时机**：存档在 `reset()` 里载入，不在构造时——这样每个 episode 都从逐字节相同的起点开始跑，A/B 对比的前提才成立。

**线程约束**：`PyBoy` 实例与 `PyBoyWorld` 全程运行在同一线程，注释明确指出**不要把 PyBoy 挪到别的线程**——`tick()` 内部要泵 SDL 事件循环，而 SDL 要求窗口创建与事件泵在同一线程，跨线程在 Windows 上会直接挂死。

构造函数中还初始化的重要状态：
- `self._closed`：窗口是否已关闭，是 world **唯一有资格宣告终止**的标志（世界没了，跑不下去；步数用尽/任务达成不归 world 判）。
- `self._cache`：帧级感知缓存，初始为 `None`。
- `self._facing`：朝向，初始为空字符串（未知）。
- `self._notes`：`inspect()` 答案的字典，初始为空。
- `self.last_frame_sha`：初始为空字符串。

### 3.3 五个 `WorldPort` 方法

#### `reset(task: Task) -> PerceptionResult`

前置条件：`task.max_steps > 0`（`assert`）。

逻辑：
1. 若有 `state_path`：打开文件、`load_state`，然后 `tick(1)`——**读档后必须 tick 一次才会重绘画面**。
2. 若无 `state_path`：`_tick(BOOT_FRAMES)`（600 帧）空转过开机动画。
3. 重置 `self._task`、`self._closed=False`、`self._cache=None`（帧缓存失效，因为画面已经变了）、`self._facing=""`、`self._notes={}`。
4. 调用 `self.observe()` 得到首个观测。
5. 断言返回的 `observation.done` 为 `False`。

`step` 字段恒不由 world 填（由 Harness 盖章）；`task` 参数目前只用于断言和"将来"按任务选起始存档（现在还没用上，恒是同一份存档）——world 不需要知道任务目标是什么，"现在要完成哪条目标"由 Harness 的目标栈保管。

#### `observe() -> PerceptionResult`

只读、幂等，同一帧不重复调视觉模型。逻辑：

1. `assert self._task is not None`（必须先 `reset()`）。
2. 调 `self._perceive()` 拿到 `(screen, terrain, calls)`。
3. **对话框误判降级**（见 3.7）：若 `overlay is DIALOG` 但 `dialog_text` 去空白后为空串，降级为 `Overlay.NONE`，并记 `misread = "dialog_without_text"`。
4. 组装 `facts` 字典，**顺序即语义**，依次是：
   - `scene`、`overlay`（降级后的值）、`screen.fields`（模型输出里其余结构化字段）
   - `dialog_text`（若有文字，且必须排最前面附近——见下方"为什么排最前"）
   - `perception_warning`（若发生了误判降级）
   - `overview`（模型给的总览描述，若有）
   - `walk_map`：`terrain.render()`，**来自模拟器内存，是这些事实里唯一 100% 精确的一项**
   - `map_id`：`terrain.map_id`
   - `where`：`terrain.place().render()`
   - `landmarks`：`terrain.render_landmarks()`（若非空）——只有类型和位置，没有名字（名字要靠走进去看见，是记忆层的事）
   - `neighbors`：`terrain.render_neighbors()`——唯一"相对我"的地形描述，是唯一能进记忆的那份（`walk_map` 的原点跟着人走，跨步骤引用会自相矛盾）
   - `facing`（若已知）
   - `options`、`cursor`（若有）
   - `inspected`（若 `self._notes` 非空，放最后，因为它是大脑自己追问出来的，优先级低于每步都有的字段，且只对这一帧有效）
5. 构造 `Observation(step=0, place=terrain.place(), summary=_summarize(screen), facts=facts, done=self._closed, success=False)`。`step`/`done`/`success` 只是占位值/由 Harness 盖章的语义（`done` 这里传的是 `self._closed`，即窗口是否已关，这是 world 唯一能宣告的终止形式）。
6. 返回 `PerceptionResult(observation=obs, calls=calls)`——`calls` 非空当且仅当这次真的调了模型，命中缓存时是空列表。

**关于 `dialog_text` 必须排最前面**的注释特别强调其代价：漏了这一项，判定器看不到对话内容，"对话框里出现母亲说的话"这类判据永远不可能成立；而决策模型看不到就会按先验编一句当成自己读到的。实测判定器自己说过："对话框内容未提供，无法确认是否为母亲说的话"。

**关于坐标系统统一**：全项目只有一套坐标（`walk_map` 行列号、`where`、`landmarks`、`known_objects` 里的 `x= y=` 都是同一套数，不需要换算），写法统一成 `x=8 y=5` 而不是 `(8,5)`，因为括号对是旧屏幕格写法，留着会让"这指的是哪一套"重新变成一个问题。

#### `inspect(focus: str) -> PerceptionResult`

对**同一帧**再问一次视觉模型，问一个具体问题；世界不推进。

前置条件：`focus` 非空（`assert`），`self._task is not None`，`self._closed` 为假。

逻辑（**整段包在 try 里**，包括取帧、读内存、渲染 prompt——因为契约是"失败不抛异常"，只护住模型调用那一行不够，`Template.render`/`substitute` 缺占位符会抛 `KeyError`，而 prompt 是最常改的文件）：

1. 取当前帧 PNG、算 sha、`read_terrain` 读地形。
2. 渲染 `inspect_prompt`（带 `focus`、`known_map`、`legend`）。
3. 调 `self._vision.describe(png, prompt)`，取文本；若为空则填占位符"（模型没说什么）"。
4. 若整个过程抛异常：`answer = "（没看清：{异常类型名}）"`，`kind` 记异常类型名。
5. 无论成败都构造一条 `record`（含 `input_tokens`/`output_tokens`——失败时填 `"0"`，因为 `PerceptionResult.calls` 的后置条件要求每条都含这两个字段，下游按 payload 累加成本的代码碰到缺字段只会 `KeyError` 或静默漏算）。
6. `self._note(focus, answer)` 写入 `_notes`（见 3.5）。
7. **不清缓存**：`observe()` 每次都从缓存里的 `ScreenState` 重新组装 `facts`，而 `_notes` 是组装时才读的，新答案自然出现在下一次 `observe()` 里。
8. 调 `self.observe()` 拿 `inner`，返回 `PerceptionResult(observation=inner.observation, calls=[record, *inner.calls])`——`calls` 按发生顺序拼：这次细看的记录在前，随后 `observe()` 自己产生的记录（通常是空列表，因为帧没变、命中缓存）跟在后面，这是因果顺序，不需要再靠记账先后去调和。

`inspect()` 和 `observe()` 的区别不在"再看一次"，而在**问的是不同的问题**：`observe()` 按帧缓存，同一帧再调返回字节完全一样没有新信息；`inspect()` 换了一份 prompt，问的是"`(7,7)` 那格到底是门还是窗"这类具体问题，同一张图不同问题才会得到不同答案。

#### `all_actions() -> list[str]`

直接返回 `list(ALL_BUTTONS)`，即 Game Boy 的八个键 `("a", "b", "up", "down", "left", "right", "start", "select")`。与状态无关，掩码是 harness 的事不在这里做。动作空间本身不增长，增长的是掩码之外的 skill library（机制二，未在本文件中）。

#### `step(action: Action) -> ToolResult`

前置条件：`self._task is not None`；`action.name in ALL_BUTTONS`；`not self._closed`（均 `assert`）。

逻辑：
1. `times = self._times(action)` 取原始连按次数（已夹到 `[1, MAX_TIMES]`，见 3.4）。
2. 应用连按夹逼规则（见 3.4）。
3. 若 `action.name in _FACING`：更新 `self._facing`（见 3.6）。
4. 循环 `times` 次：`self._pyboy.button(action.name, delay=PRESS_FRAMES)` 然后 `self._tick(WITHIN_ACTION_FRAMES)`（每次按完推进 60 帧 = 1 秒）。
5. 循环结束后 `self._tick(AFTER_ACTION_FRAMES)`（再推进 120 帧 = 2 秒），等世界落定再感知。
6. `self._notes = {}`——细看的答案只对那一帧有效，一旦世界推进就清空（这是 `_notes` 唯一的清空点）。
7. **不清 `_cache`**：`_perceive()` 自己按帧哈希判断，画面真变了自然会重新调模型；若按键后画面没变（对着空地按 a、朝墙走），清缓存就是白花一次感知还会引入噪声——实测连着四步 frame sha 一模一样，模型却给出了不同的 `overview`，其中一步把地图下方的黑边认成了对话框，同一帧只问一次这类抖动直接消失。
8. `result = self.observe()`——由于 `_cache` 刚被上一帧内容占据（但 sha 会变，因为世界已推进），这是本步唯一一次真感知。
9. 构造提示语 `note`：若 `times > 1` 则标注"（按了 N 次）"；若原始请求次数 `asked > times`（即发生了夹逼），改写为"（{原因}，连按 {asked} 次被夹成 1 次）"，原因是 `"a 只能一次一次按"`（交互键）或 `"对话框开着"`（对话框场景）。**夹了要说**，否则大脑会以为自己连按了 N 次，而实际只走了一次，它下一步的推理就建立在错的前提上。
10. 返回 `ToolResult(message=obs.summary + note, observation=obs, calls=result.calls)`。

该方法**不报告"这一下有没有生效"**：那需要对比前后两次观察，是上层（记忆层，两头各存一份完整快照）的事；world 只负责"我按了，世界推进了"。

### 3.4 连按（`times`）的夹逼规则

`_times(action)` 静态方法：从 `action.args["times"]` 取值，非法/无法转 int 时返回 1；否则 `max(1, min(n, MAX_TIMES))`，`MAX_TIMES = 8`。**不因次数写错而判整个动作失败**——动作名是对的，只是参数不合规范，为它跑一轮重试不划算（判据同 ```json 包裹）。

`MAX_TIMES=8` 存在的理由：模型会写 `"times": "100"`；连按期间 agent 看不见中间状态，撞墙了也会把剩下几次按完（时序抽象的经典取舍，次数是宏动作的原始形态）。收益是省感知调用：走 5 格从 5 次 VLM 调用变成 1 次，把成本和延迟都砍到五分之一。

在 `step()` 里，实际执行前还有一层**二次夹逼**：

```python
if action.name == INTERACT_KEY or (times > 1 and self._dialog_is_open()):
    times = 1
```

三条具体规则及各自背后的实测坑：

1. **交互键（`a`）恒被夹成 1**：因为一步只感知一次，连按会把中间那几帧整个吃掉，而 `a` 产出的恰恰是全项目最要紧的证据——对话框文字。具体代价两条：
   - 判据最常用的就是对话内容（比如"对话框里出现母亲说的话"）；连按三次推完整段对话，那几句话一帧都没被看到，最后一次还会把对话框关掉——判定器看到一个没有对话框的画面，**一局本该成功的 episode 被静默记成失败**。
   - 档案里那一格的 `lines` 只拿得到最后一句，中间几句直接丢，而"这是谁"往往写在第一句里。

2. **对话框已经开着时，连按被夹成 1**：这是第二条件 `times > 1 and self._dialog_is_open()`。

3. **早一版的坑**：早期实现只在"对话框已经开着"时夹（即只有上面第 2 条，没有第 1 条对 `a` 的无条件夹逼）。这漏掉了最常见的情形：**对话框还没开**，模型对着 NPC 连按三次 `a`——第一次开对话框、后两次推完整段对话，一句话都没记下。因为 `a` 的收益全在中间那几帧上，**连按对它从来没有意义**，所以最终规则是不管对话框状态如何，`a` 恒为 1。

4. **方向键不夹**：沿直线走几格是连按省步数的正当手段，中间帧本来就没有额外证据（走过的格子长什么样并不重要，重要的是走到哪里），所以方向键的 `times` 保持原值（在 `MAX_TIMES` 范围内）。

### 3.5 朝向（`facing`）的维护

朝向**完全从按键推导，不问模型**：

- `_FACING = BUTTON_FACING`（定义在 `schemas/core.py`，因为工具层也要用同一张表去算"这一步走的是哪个方向"）。
- 在 `step()` 里，若 `action.name in _FACING`，则 `self._facing = _FACING[action.name]`。
- 朝向要紧是因为 `a` 键作用在**面朝的那一格**上：不知道朝向就不知道 `a` 会调查到什么。
- 初始为空字符串（未知）；开局和过场之后都是未知，按一次方向键就确定。空值时 `observe()` 组装 `facts` 不会写入 `facing` 字段（`if self._facing:` 判断）。

### 3.6 `_notes`（`inspect` 答案）的生命周期

- **写入时机**：`inspect(focus)` 成功或失败都会调 `self._note(focus, answer)` 写入，无论是模型真答复还是"（没看清：…）"的降级答案。
- **清空时机**：唯一的清空点是 `step()` 里的 `self._notes = {}`——世界一旦推进，这些答案描述的是上一帧，留到下一帧就是过期事实，而过期事实比没有事实更糟（大脑分不出它是新的还是旧的）。`reset()` 也会清空（`self._notes = {}`），是因为整个世界状态被重置。
- **上限**：`MAX_NOTES = 4`。`_note()` 内部用 `dict`（不是 `list`）按 `focus` 去重：
  - 同一 focus 再问一次，`self._notes.pop(focus, None)` 先删旧的再插入新的（覆盖时也要换到队尾，保证插入顺序反映"最近问过"）。
  - 超过 `MAX_NOTES` 条时，`while len(self._notes) > MAX_NOTES: self._notes.pop(next(iter(self._notes)))`——丢掉最早插入的那条，因为大脑最近关心的问题更可能还在用。
- **为什么需要上限**：`inspect()` 不推进世界，所以 `step()` 的清空机制永远轮不到它——理论上一帧里能一直问下去。而这段"inspected"文字**同时进决策 prompt 和判定 prompt**，实测连问 6 次同一个问题，`facts["inspected"]` 从 0 涨到 231 字符，同一条答案被原样拼了 6 遍——重复的事实会被模型当成强证据，比过期事实更糟。
- **写法上的补充设计原则**：`_notes` 是"只增不改"式地作为单独的 `facts["inspected"]` 键，**不去覆盖 `landmarks` 等既有字段**。合并两份可能冲突的语义描述需要一套优先级规则，而那套规则本身就会出错；并排放着让大脑自己读，反而是大脑（LLM）擅长的事。

### 3.7 `_dialog_is_open()` 与对话框误判降级

#### `_dialog_is_open()`

```python
def _dialog_is_open(self) -> bool:
    return self._cache is not None and self._cache[1].overlay is Overlay.DIALOG
```

读的是缓存里的 `ScreenState`，**不额外调模型**。缓存为空（刚 `reset()`，或上一步刚推进过、还没重新感知）时保守地当作"没有对话框"——那时下一次 `observe()` 才会真正知道；夹连按是为了不丢证据帧，少夹一次的代价远小于为它多调一次感知。它被 `step()` 用来判断第 3.4 节中规则 2 是否触发。

#### 对话框误判降级（`misread` / `dialog_without_text`）

在 `observe()` 里，拿到 `(screen, terrain, calls)` 后：

```python
misread = ""
if overlay is Overlay.DIALOG and not text:
    overlay, misread = Overlay.NONE, "dialog_without_text"
```

即：模型说场景里有对话框（`overlay == DIALOG`），但 `dialog_text` 去空白后是空字符串——**"说有对话框却一个字都没抄出来"，判定为它把别的东西看成了对话框**。这时把 `overlay` 强制降级为 `Overlay.NONE`，并把 `perception_warning = "dialog_without_text"` 写入 `facts`。

**实测依据**：室内地图下方的黑色边界被模型认成对话框，而同一帧（frame sha 一模一样）上一步模型判的是 `none`——即同一张图两次判断不一致，其中一次明显是误判。

**为什么这条交叉检验成立**：它不需要任何新的输入——只是拿模型自己的两个输出（`overlay` 判断与 `dialog_text` 抄写）对账。而 `overlay` 决定动作掩码，错一次大脑就会拿到一组它按不出效果的动作（比如掩码给出"继续对话"相关的按键，但根本没有对话框），所以这条纠错很有必要。

---

## 4. 与 `VisionProvider` 的交互

`PyBoyWorld` 持有一个 `VisionProvider` 实例（构造时传入），通过它唯一的方法 `describe(image_png: bytes, prompt: str) -> VisionCompletion` 完成所有感知调用。共有两处调用点：

### 4.1 `_perceive()`（主感知，`observe()`/`reset()` 间接触发）

- **传什么**：当前帧的 PNG 字节（`self._frame_png()`）+ 渲染好的主感知 prompt（`self._prompt.render(known_map=terrain.render())`，即把地形骨架文本嵌入 prompt，让模型在已经正确的骨架上标语义，而不是自己判断能不能走）。
- **收到什么**：`VisionCompletion(text, input_tokens, output_tokens)`。`text` 经 `parse_screen()` 解析成 `ScreenState`（容忍 ` ```json ` 包裹，其余解析失败一律返回 `None` 交给调用方重试）。
- **重试**：最多 `self._retries`（即 `max_perceive_retries`）次，每次都记一条调用日志（`frame_sha`/`prompt_sha`/`input_tokens`/`output_tokens`/`latency_ms`/`attempt`/`ok`/`raw`）。全部失败则抛 `PerceptionFailure`，**不返回空白状态兜底**——那会让大脑基于假观测决策，且这类失败必须能在 replay 里被统计到。
- 成功则写入 `self._cache = (sha, screen, terrain)` 并返回。

### 4.2 `inspect()`（追问，同一帧换一份 prompt）

- **传什么**：同一帧的 PNG（重新截取，非复用缓存图像字节，但会算出与之前相同的 sha）+ `inspect_prompt.render(focus=focus, known_map=terrain.render(), legend=terrain_legend())`。
- **收到什么**：同样是 `VisionCompletion`；文本被当作最终答案（去空白，空则填占位符），不再走 `parse_screen`（不要求是结构化 `ScreenState`，因为 `inspect` 问的是开放式问题）。
- 失败（异常）时不重试，直接把异常类型名写进答案文本，且这条记录的 `ok` 字段标 `false`。

两处都遵循 `VisionProvider.describe` 契约里的关键警告：**实现方必须校验图片确实被消费了**（token 数下界），因为已知有网关会静默丢图但仍返回一段"读起来合理"的描述——这属于 `VisionProvider` 实现自身的职责（抛 `ImageNotDelivered`），不是 `PyBoyWorld` 在调用点做的事，但 `PyBoyWorld` 依赖这个契约来保证 `input_tokens`/`output_tokens` 字段的可信度（记入 `calls`，供下游按 payload 核算成本、排查感知错误)。

---

## 5. `_perceive()`：帧哈希缓存机制完整原理

```python
def _perceive(self) -> tuple[ScreenState, TerrainMap, list[dict[str, str]]]
```

### 5.1 完整流程

1. 截取当前帧 PNG（`self._frame_png()`），计算 `sha = hashlib.sha256(png).hexdigest()[:12]`，写入 `self.last_frame_sha`（不论缓存命中与否都更新——它代表的是"最近一次观测所依据的那一帧"，供追查感知错误用）。
2. **缓存命中判定**：若 `self._cache is not None and self._cache[0] == sha`，直接返回 `(self._cache[1], self._cache[2], [])`——**什么账都不产生，因为没调模型**。
3. 未命中：`read_terrain(self._pyboy.memory)` 读地形骨架，渲染主 prompt。
4. 在 `[1, self._retries]` 范围内循环调 `self._vision.describe(png, prompt)`，尝试 `parse_screen`：
   - 每次尝试都追加一条调用记录到 `calls` 列表。
   - 一旦解析成功：`self._cache = (sha, screen, terrain)`，返回 `(screen, terrain, calls)`。
5. 全部重试失败：抛 `PerceptionFailure(self._retries, f"unparsable output: {last!r}")`。

### 5.2 重试逻辑

`max_perceive_retries`（默认 2）控制最多尝试几次。每次失败原因只有一种——`parse_screen` 返回 `None`（模型输出不是合法的 `ScreenState` JSON，且不是常见的 ` ```json ` 包裹偏差）。重试之间不改变 prompt 或图片，纯粹是指望模型下一次输出格式正确的 JSON。重试期间产生的每一次调用（无论成败）都计入 `calls`，因此 `calls` 长度可能大于 1，供上游核算真实花费的模型调用次数与 token。

### 5.3 缓存键为什么是帧哈希而不是别的

因为契约要求 `observe()` "只读、幂等"，而每次真调模型都有 token/延迟成本。帧的像素内容（PNG 字节的 sha256）是判断"世界是否发生了肉眼可见变化"的天然、精确的键：只要 PyBoy 输出的画面字节没变，就认为没有新信息值得重新花钱去问模型。`step()` 特意不清空缓存（见 3.3 `step()` 步骤 7），完全依赖这个哈希判定自然失效。

### 5.4 为什么现在返回三元组而不是 `_pending_calls` 缓冲区（最近一次重构）

这是 `interfaces/world.py` 文档里专门论证过的设计决策，`pyboy_world.py` 里的实现与之呼应。

**问题的根源**：感知的开销记录（调用了几次模型、token、延迟、原始输出）必须被记下来进 trace（用于成本核算、排查"读错的观测是哪一帧"、阶段性把 VLM 输出和真值对标），但这些开销信息**又不该放进 `Observation`**——那是"大脑看的东西"，大脑不该知道 token 数，而且 `Observation` 是跨层契约，随便加字段等于改接口。

**旧方案（`_pending_calls` 缓冲区 + `drain_calls()`）**：产生调用记录的地方（`_perceive()`）先把记录攒进 `self._pending_calls`，Harness 之后单独调 `drain_calls()` 取走并清空。这是"生产/消费分离、靠可变状态搭桥"的设计。文档明确指出：

> 这个设计本身就是 bug 的温床——缓冲区什么时候清、被谁清，两个方向都能错。

具体隐患：`_perceive()` 可能被 `reset()`/`observe()`/`inspect()`/`step()` 多处共用地间接调用，如果 `drain_calls()` 被调用的时机和产生记录的时机没对齐（比如两次 `_perceive()` 之间忘了 drain，或者 drain 早了漏了后一次的记录，或者 drain 晚了把不该属于这次调用的旧记录也带出去），trace 里的账就会算错，而这种错误往往很难在测试里稳定复现。

**新方案（`calls` 跟着返回值走）**：`_perceive()` 直接返回 `(ScreenState, TerrainMap, calls)` 三元组，调用记录**作为返回值的一部分直接交出去，不再攒进实例状态**。谁调用了 `_perceive()`，`calls` 就跟着这次调用的返回值一路原样向上传：

```
_perceive() → observe() → reset() / inspect()
_perceive() → observe() → step()（经由 ToolResult.calls）
```

`inspect()` 里体现得最清楚：它自己产生一条 `record`（细看的调用记录），然后调 `self.observe()` 拿到 `inner.calls`（通常是空列表，因为帧没变命中缓存），最终按因果顺序拼成 `[record, *inner.calls]`。`step()` 同理，`calls` 就挂在已经存在的 `ToolResult` 上，不必新开一个类型。

**这个方案的优点**：
- 不需要任何跨调用的可变状态，也就不存在"谁来得早谁来得晚"的记账错位问题。
- `calls` 的正确性由普通的函数返回值传递保证，不依赖"记得在正确的时机去 drain"这种容易遗忘的操作序。
- 不产生模型调用的世界（假设的其他 `WorldPort` 实现）只需返回空列表即可满足契约，这不是负担。

一句话回答"为什么需要 `_pending_calls`"这个问题本身：**其实并不需要**——它是旧设计遗留的产物，用来解决"感知开销要进 trace 但不能进 Observation"这个真问题，但选择的手段（跨调用可变缓冲区 + 显式 drain）引入了比它解决的问题更多的错误可能性，因此被替换为"让 `calls` 随返回值自然向上传播"的现方案。

---

## 6. 其他内部细节速查

- **`_summarize(s: ScreenState) -> str`**：给大脑读的极简自然语言状态，只是 prompt 的上下文开头，详细字段都在 `facts` 里。按 `Scene` 枚举给一句"你在……"的话，再视 `overlay` 追加对话框摘录或选项列表。
- **`parse_screen(text)`**：把模型原始文本解析为 `ScreenState`，容忍 ` ```json ` 包裹（模型最常见的格式偏差），其余解析失败一律返回 `None`，不做其它兜底。
- **`_tick(frames)`**：逐帧调用 `self._pyboy.tick(1)`，不是批量 `tick(n)`——因为 `tick(n)` 只在最后限速一次，批量调用在 `watch` 模式下画面会一跳一跳，逐帧才平滑；无头模式不限速，逐帧的额外开销可忽略。若某次 `tick(1)` 返回假值（窗口被关），置 `self._closed = True` 并立即返回——这是 world 唯一的终止权。
- **`PRESS_FRAMES=10`**（按键按住的帧数）、**`WITHIN_ACTION_FRAMES=60`**（连按时每次按完推进 1 秒）、**`AFTER_ACTION_FRAMES=120`**（整个动作结束后再推进 2 秒才感知）、**`BOOT_FRAMES=600`**（无存档时空转越过开机 logo）。
- **导入期防护性断言**：模块顶层有一条 `assert`，检查 `OVERLAY_ACTIONS`（定义在 `schemas/observation.py`，掩码表）里出现的每个键都在 `ALL_BUTTONS` 里。这条**在导入时查，不留给测试**：两张表分处 `schemas` 和 `world` 两个文件，改了一边忘了另一边时，harness 会交出一个世界不认识的动作，而错误要等到大脑选中它、`step()` 真正执行时才会炸——离病因隔了三层，导入期断言把这类错误提前到进程启动那一刻。
- **`stop()`**：`self._pyboy.stop()`，非 `WorldPort` 协议方法，是资源释放的收尾。
