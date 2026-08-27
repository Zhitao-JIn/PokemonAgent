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
| `WorldPort` / `PyBoyWorld`（本模块） | 世界本身能做什么：`reset`/`observe`/`step`/`all_actions` | **是**，所有调 VLM、读内存、组装 `Observation.facts` 的逻辑都在这里 |
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

- **分层**：`observe()` 的契约要求交出含 `status` 与 `facts` 的 `Observation`，而这必须调 VLM——所以感知只能在 world 里。但掩码是 harness 的策略，依赖的 `overlay`/`scene` 是感知产物；解法是**把 `scene` 与 `overlay` 放进 `Observation.facts`**，harness 读 `facts` 做掩码不算越界（`facts` 本就是 `Observation` 的公开部分）。
- **时序：同步 + 固定缓冲**，流程是"按一次键 → 推进 `WITHIN_ACTION_FRAMES` 帧 →（链上还有下一次按键，重复）→ 推进 `AFTER_ACTION_FRAMES` 帧 → 感知"。整条动作链只在**结尾感知一次**（见 3.3 `step()`）。
  - 曾用"连续 N 帧不变"判稳定，不可行：草丛、水面、NPC 走动、闪烁光标、战斗呼吸动画很多画面根本不会静止，等稳定会大面积超时。
  - 曾把模拟器放进后台线程异步跑，让模型思考时间充当天然等待；动画问题自己消失，但代价是**不可复现**（同一存档跑两次结果不同），且线程/队列/条件变量/退出唤醒的复杂度全是为了这一个好处。
  - 固定缓冲用远少的代码换到同一效果的九成，还顺带拿回了可复现性。剩下的风险（偶尔感知到动画中间帧）是概率问题不是正确性问题，可测量但不必优先解决。
- **不判断动作有没有生效**：画面本来就在动，像素比对量不出因果；动作没生效的话下一步观测会照实反映，由大脑自己纠正。
- **不判成败、不数步**：任务达成需要一次独立模型调用，world 不该认识 LLM；走了几步是循环的账，同一世界要跑不同步数上限的任务。这两件事都在 `Harness`。
- **`observe()` 每次都是真感知**：每调一次就是一次 VLM 调用，所以调用点必须
  受控——只有 `reset()` 和 `step()` 的结尾会调它，一帧恰好一次。曾经它按帧缓存，
  因为上层同一帧要问四次；那个结构已经改掉了（见 5.3）。

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
| `watch` | 是否开窗口实时观看。为 `True` 时用 `window="SDL2"`，否则 `window="null"`（无头）。也决定 `set_emulation_speed` 是否受 `speed` 控制还是恒为 0（无头不限速）。 |
| `speed` | `watch=True` 时的模拟器播放速度。`watch=False` 时该参数不生效（速度设为 0，即不限速全速跑）。 |

**存档载入时机**：存档在 `reset()` 里载入，不在构造时——这样每个 episode 都从逐字节相同的起点开始跑，A/B 对比的前提才成立。

**线程约束**：`PyBoy` 实例与 `PyBoyWorld` 全程运行在同一线程，注释明确指出**不要把 PyBoy 挪到别的线程**——`tick()` 内部要泵 SDL 事件循环，而 SDL 要求窗口创建与事件泵在同一线程，跨线程在 Windows 上会直接挂死。

构造函数中还初始化的重要状态：
- `self._closed`：窗口是否已关闭，是 world **唯一有资格宣告终止**的标志（世界没了，跑不下去；步数用尽/任务达成不归 world 判）。

### 3.3 四个 `WorldPort` 方法

#### `reset(task: Task) -> PerceptionResult`

前置条件：`task.max_steps > 0`（`assert`）。

逻辑：
1. 若有 `state_path`：打开文件、`load_state`，然后 `tick(1)`——**读档后必须 tick 一次才会重绘画面**。
2. 若无 `state_path`：`_tick(BOOT_FRAMES)`（600 帧）空转过开机动画。
3. 重置 `self._task`、`self._closed=False`。
4. 调用 `self.observe()` 得到首个观测。
5. 断言返回的 `observation.done` 为 `False`。

`step` 字段恒不由 world 填（由 Harness 盖章）；`task` 参数目前只用于断言和"将来"按任务选起始存档（现在还没用上，恒是同一份存档）——world 不需要知道任务目标是什么，"现在要完成哪条目标"由 Harness 的目标栈保管。

#### `observe() -> PerceptionResult`

只读、幂等，同一帧不重复调视觉模型。逻辑：

1. `assert self._task is not None`（必须先 `reset()`）。
2. 调 `self._perceive()` 拿到 `(screen, terrain, calls)`。
3. **对话框误判降级**（见 3.6）：若 `overlay is DIALOG` 但 `dialog_text` 去空白后为空串，降级为 `Overlay.NONE`，并记 `misread = "dialog_without_text"`。
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
   - `facing`（若 `terrain.facing` 非空，见 3.5）
   - `options`、`cursor`（若有）
5. 构造 `Observation(step=0, place=terrain.place(), status=_status_line(screen), facts=facts, done=self._closed, success=False)`。`step`/`done`/`success` 只是占位值/由 Harness 盖章的语义（`done` 这里传的是 `self._closed`，即窗口是否已关，这是 world 唯一能宣告的终止形式）。
6. 返回 `PerceptionResult(observation=obs, calls=calls)`——`calls` 记的是这次感知产生的每一次模型调用（含重试）。

**关于 `dialog_text` 必须排最前面**的注释特别强调其代价：漏了这一项，判定器看不到对话内容，"对话框里出现母亲说的话"这类判据永远不可能成立；而决策模型看不到就会按先验编一句当成自己读到的。实测判定器自己说过："对话框内容未提供，无法确认是否为母亲说的话"。

**关于坐标系统统一**：全项目只有一套坐标（`walk_map` 行列号、`where`、`landmarks`、`known_objects` 里的 `x= y=` 都是同一套数，不需要换算），写法统一成 `x=8 y=5` 而不是 `(8,5)`，因为括号对是旧屏幕格写法，留着会让"这指的是哪一套"重新变成一个问题。

#### 这里曾经有一个 `inspect(focus)`

它对**同一帧**再问一次视觉模型（换 `inspect_focus` 那份 prompt，问"`x=7 y=7` 那格
到底是门还是窗"这类具体问题），世界不推进，答案攒进 `_notes`，再作为
`facts["inspected"]` 并进下一次 `observe()`。整条链路——`PyBoyWorld.inspect()`、
`_note()`/`_notes`/`MAX_NOTES`、构造参数 `inspect_prompt_name`、
`prompts/inspect_focus.md`，连同 `WorldPort.inspect` 协议方法——**都已删除**。

留下来的经验（删之前踩过的坑，换个形式还会再踩）：

- `inspect()` 不推进世界，所以 `step()` 的"世界一动就清空"机制永远轮不到它，
  理论上一帧里能一直问下去，于是不得不加 `MAX_NOTES = 4` 这个上限。
  实测连问 6 次同一个问题，`facts["inspected"]` 从 0 涨到 231 字符，
  同一条答案被原样拼了 6 遍——**重复的事实会被模型当成强证据**，比过期事实更糟。
- 答案只对那一帧有效：世界一推进就是过期事实，而过期事实比没有事实更糟
  （大脑分不出它是新的还是旧的）。所以它需要一个明确的清空点，
  而"什么时候清"正是这类跨调用可变状态最容易出错的地方（同 5.4 的 `_pending_calls`）。
- 它也是唯一让 `observe()` 的"幂等"打折扣的东西：调过 `inspect()` 之后，
  同一帧的 `observe()` 返回值会多一条 `inspected`——幂等只对模型调用成立、
  对返回值不成立。删掉之后这条例外没有了。

`EventType.INSPECT` 这个枚举成员**仍然保留**，但只为让旧 trace 文件回放时还看得见
那类事件，不再有任何代码产生它。

#### `all_actions() -> list[str]`

直接返回 `list(ALL_BUTTONS)`，即 Game Boy 的八个键 `("a", "b", "up", "down", "left", "right", "start", "select")`。与状态无关，掩码是 harness 的事不在这里做。动作空间本身不增长，增长的是掩码之外的 skill library（机制二，未在本文件中）。

#### `step(action: Action) -> ToolResult`

前置条件：`self._task is not None`；`not self._closed`；`action.segments()` 里**每一段**的 `name` 都在 `ALL_BUTTONS` 中（均 `assert`）。

逻辑：
1. `segments = action.segments()` 拿到规范化的动作链（见 3.4）。
2. 逐段、段内逐次执行：`self._pyboy.button(segment.name, delay=PRESS_FRAMES)` 然后 `self._tick(WITHIN_ACTION_FRAMES)`。
3. 整条链跑完后 `self._tick(AFTER_ACTION_FRAMES)`，等世界落定再感知。
4. 结尾 `self.observe()` 感知一次——**这是整条动作链唯一的一次真感知**，返回的观测
   会沿 `ToolResult` → `pending_observation` 一路传到下一步的 `look`。
5. `result = self.observe()`——**整条链唯一的一次真感知**。
6. 返回 `ToolResult(observation=obs, calls=result.calls)`。

**一次决策 = 一次感知。** 段与段之间不感知：每次感知都是一次视觉模型调用，
`up×4 -> down×2` 要是每按一次感知一次，一步就是六次调用、十几秒，而中间那五帧
没有任何会被用到的信息——多段链按规则链体只能是移动键（`up`/`down`），链尾可带一个 `a`，
走过的格子长什么样并不重要，重要的是走到哪里。

**收到什么就按什么，world 不改写动作。** 这里曾经有一层"二次夹逼"：
`step()` 里按 `if action.name == INTERACT_KEY or (times > 1 and self._dialog_is_open())`
把次数改成 1，并在返回的 message 里补一句"（…，连按 N 次被夹成 1 次）"。
规则本身是对的（理由见 3.4），但**夹在执行层是错的地方**：大脑交出去的链和真正
发生的链对不上，而它下一步的推理建立在前者上，所以还得反过来在 message 里把
"我偷偷改了你的动作"告诉它。现在这条规则前移到 `Brain._parse`——解析期就把 `a`
的 `times` 定死为 1，交给 world 的链**就是真正会发生的那条链**，
`_times()`、`_clamped()`、`_dialog_is_open()` 和那句提示语于是一起消失了。

**`ToolResult.message` 也一并删了**：它当年的内容是 `obs.summary` 加上那句夹逼提示。
提示没了之后它只剩把 `observation.status` 原样抄一遍，而下游本来就拿得到
`observation`——同一句话存两份，迟早会有一份先过期。

该方法**不报告"这一下有没有生效"**：那需要对比前后两次观察，是上层（记忆层，两头各存一份完整快照）的事；world 只负责"我按了，世界推进了"。

### 3.4 动作链与连按（`times`）

一个 `Action` 带着 `sequence: list[ActionSegment]`，每段是 `name` + `times`；
`Action.segments()` 交出规范化后的链，`Action.describe()` 把它渲染成
`up×4 -> down×2` 这样一行（进 trace 和记忆）。约束都在 world 之外定死：

- `times` 取值 1-`MAX_TIMES`，`MAX_TIMES = 8` 定义在 `schemas/action.py`
  （数据契约），`Brain._parse` 校验外部输入时用的是同一个常量——**同一个数
  两个执行点必须同源**，否则模型给 100 时会得到一个自相矛盾的系统。
- 顶层的 `action`/`args` 写法**不再被接受**（解析期就拒），链是唯一的形状。
- **多段链只能由 `up`/`down` 组成**，其余按键只能单段。

`MAX_TIMES=8` 存在的理由：模型会写 `"times": "100"`；连按期间 agent 看不见中间状态，
撞墙了也会把剩下几次按完（时序抽象的经典取舍，次数是宏动作的原始形态）。
收益是省感知调用：走 5 格从 5 次 VLM 调用变成 1 次，把成本和延迟都砍到五分之一。

**`a` 恒为 1，但这条规则不在 world 里**——它在 `Brain._parse`，解析期直接把
`INTERACT_KEY` 的 `times` 写死成 1。理由（这段实测经验值得留着）：

1. 一步只感知一次，连按会把中间那几帧整个吃掉，而 `a` 产出的恰恰是全项目最要紧的
   证据——对话框文字。具体代价两条：
   - 判据最常用的就是对话内容（比如"对话框里出现母亲说的话"）；连按三次推完整段
     对话，那几句话一帧都没被看到，最后一次还会把对话框关掉——判定器看到一个没有
     对话框的画面，**一局本该成功的 episode 被静默记成失败**。
   - 档案里那一格的 `lines` 只拿得到最后一句，中间几句直接丢，而"这是谁"往往写在第一句里。
2. **早一版的坑**：更早的实现只在"对话框已经开着"时夹（world 里的 `_dialog_is_open()`）。
   这漏掉了最常见的情形：**对话框还没开**，模型对着 NPC 连按三次 `a`——第一次开对话框、
   后两次推完整段对话，一句话都没记下。因为 `a` 的收益全在中间那几帧上，
   **连按对它从来没有意义**，所以规则改成不管对话框状态如何，`a` 恒为 1；
   而一旦不再依赖"对话框现在开没开"这个感知结果，这条规则就不必留在 world 里了。
3. **方向键不夹**：沿直线走几格是连按省步数的正当手段，中间帧本来就没有额外证据
   （走过的格子长什么样并不重要，重要的是走到哪里）。

### 3.5 朝向（`facing`）从 RAM 读

- `ram.read_facing(mem)` 读精灵表 `+9`（0/4/8/12 → south/north/west/east），
  结果放进 `TerrainMap.facing`，`observe()` 组装 `facts["facing"]` 时直接取。
- 朝向要紧是因为 `a` 键作用在**面朝的那一格**上：不知道朝向就不知道 `a` 会调查到什么。
- 读不出四个已知值之一时返回空串，`facts` 里就不写这个键（正常情况下不会发生）。

**这里原来是从按键推的**：`step()` 里按了方向键就更新 `self._facing`。
那个推论本身没错（撞墙时人也会转过去），但它有两个洞：开局和过场之后朝向是未知的，
而且它不在存档里，checkpoint 恢复不回来（`harness/SPEC.md` 1.4）。
`+9` 这个字节的含义在 `ram.py` 的精灵表说明里一直写着，只是没读。
`BUTTON_FACING` 仍然留着，但它现在只回答"这一步往哪个方向按了"（工具层算
语义记忆的 attempts 键要用），不再是"现在面朝哪"的来源。

### 3.6 对话框误判降级（`misread` / `dialog_without_text`）

在 `observe()` 里，拿到 `(screen, terrain, calls)` 后：

```python
misread = ""
if overlay is Overlay.DIALOG and not text:
    overlay, misread = Overlay.NONE, "dialog_without_text"
```

即：模型说场景里有对话框（`overlay == DIALOG`），但 `dialog_text` 去空白后是空字符串——**"说有对话框却一个字都没抄出来"，判定为它把别的东西看成了对话框**。这时把 `overlay` 强制降级为 `Overlay.NONE`，并把 `perception_warning = "dialog_without_text"` 写入 `facts`。

**实测依据**：室内地图下方的黑色边界被模型认成对话框，而同一帧（frame sha 一模一样）上一步模型判的是 `none`——即同一张图两次判断不一致，其中一次明显是误判。

**为什么这条交叉检验成立**：它不需要任何新的输入——只是拿模型自己的两个输出（`overlay` 判断与 `dialog_text` 抄写）对账。而 `overlay` 决定动作掩码，错一次大脑就会拿到一组它按不出效果的动作（比如掩码给出"继续对话"相关的按键，但根本没有对话框），所以这条纠错很有必要。

**这里曾经还有一个 `_dialog_is_open()`**：读上一次感知出的 `ScreenState` 判断对话框开没开，
不额外调模型，专供 `step()` 的连按二次夹逼用。夹逼规则前移到 `Brain._parse` 之后
（见 3.4），它没有了唯一的调用方，一并删除。

---

## 4. 与 `VisionProvider` 的交互

`PyBoyWorld` 持有一个 `VisionProvider` 实例（构造时传入），通过它唯一的方法 `describe(image_png: bytes, prompt: str) -> VisionCompletion` 完成所有感知调用。现在只剩**一处**调用点（曾经还有一处是 `inspect()`，已随细看链路删除）：

### 4.1 `_perceive()`（主感知，`observe()`/`reset()`/`step()` 间接触发）

- **传什么**：当前帧的 PNG 字节（`self._frame_png()`）+ 渲染好的主感知 prompt（`self._prompt.render(known_map=terrain.render())`，即把地形骨架文本嵌入 prompt，让模型在已经正确的骨架上标语义，而不是自己判断能不能走）。
- **收到什么**：`VisionCompletion(text, input_tokens, output_tokens)`。`text` 经 `parse_screen()` 解析成 `ScreenState`（容忍 ` ```json ` 包裹，其余解析失败一律返回 `None` 交给调用方重试）。
- **重试**：最多 `self._retries`（即 `max_perceive_retries`）次，每次都记一条调用日志（`prompt_sha`/`input_tokens`/`output_tokens`/`latency_ms`/`attempt`/`ok`/`raw`）。全部失败则抛 `PerceptionFailure`，**不返回空白状态兜底**——那会让大脑基于假观测决策，且这类失败必须能在 replay 里被统计到。
- 成功则直接返回 `(screen, terrain, calls)`。

这处调用遵循 `VisionProvider.describe` 契约里的关键警告：**实现方必须校验图片确实被消费了**（token 数下界），因为已知有网关会静默丢图但仍返回一段"读起来合理"的描述——这属于 `VisionProvider` 实现自身的职责（抛 `ImageNotDelivered`），不是 `PyBoyWorld` 在调用点做的事，但 `PyBoyWorld` 依赖这个契约来保证 `input_tokens`/`output_tokens` 字段的可信度（记入 `calls`，供下游按 payload 核算成本、排查感知错误)。

---

## 5. `_perceive()`：一次真感知，没有缓存

```python
def _perceive(self) -> tuple[ScreenState, TerrainMap, list[dict[str, str]]]
```

### 5.1 完整流程

1. 截取当前帧 PNG（`self._frame_png()`）。
2. `read_terrain(self._pyboy.memory)` 读地形骨架，渲染主 prompt。
3. 在 `[1, self._retries]` 范围内循环调 `self._vision.describe(png, prompt)`，尝试 `parse_screen`：
   - 每次尝试都追加一条调用记录到 `calls` 列表。
   - 一旦解析成功：返回 `(screen, terrain, calls)`。
4. 全部重试失败：抛 `PerceptionFailure(self._retries, f"unparsable output: {last!r}")`。

**每次调用都是一次真感知。** 调用路径只有两条——`reset()` 和 `step()` 结尾的
`observe()`，一帧恰好一次，所以没有要缓存的东西。

### 5.2 重试逻辑

`max_perceive_retries`（默认 2）控制最多尝试几次。每次失败原因只有一种——`parse_screen` 返回 `None`（模型输出不是合法的 `ScreenState` JSON，且不是常见的 ` ```json ` 包裹偏差）。重试之间不改变 prompt 或图片，纯粹是指望模型下一次输出格式正确的 JSON。重试期间产生的每一次调用（无论成败）都计入 `calls`，因此 `calls` 长度可能大于 1，供上游核算真实花费的模型调用次数与 token。

### 5.3 这里曾经有一个按帧哈希的缓存

`_cache: tuple[str, ScreenState, TerrainMap]`，键是 PNG 字节的 sha256 前 12 位。
它存在的原因是**同一帧会被感知四次**：`Harness._look` 一次、`get_action_space()`
一次、`step()` 结尾一次、下一步 `_look` 又一次。缓存把其中三次挡掉，于是稳态下
每步只花一次感知的钱。

**但那是在补一个结构问题**——同一帧本来就不该被问四遍。而且缓存掩盖了另一件事：
「记忆里的 `after` 和下一步的观测相等」当时只是碰巧成立（靠"中间没人 tick 世界"），
没有任何断言守着。

改成一帧只感知一次之后，缓存没有东西可缓存，帧哈希也没有东西可比较，两个一起删了。
完整论证见 `tools/SPEC.md` 2.7。

### 5.4 为什么现在返回三元组而不是 `_pending_calls` 缓冲区（最近一次重构）

这是 `interfaces/world.py` 文档里专门论证过的设计决策，`pyboy_world.py` 里的实现与之呼应。

**问题的根源**：感知的开销记录（调用了几次模型、token、延迟、原始输出）必须被记下来进 trace（用于成本核算、排查"读错的观测是哪一帧"、阶段性把 VLM 输出和真值对标），但这些开销信息**又不该放进 `Observation`**——那是"大脑看的东西"，大脑不该知道 token 数，而且 `Observation` 是跨层契约，随便加字段等于改接口。

**旧方案（`_pending_calls` 缓冲区 + `drain_calls()`）**：产生调用记录的地方（`_perceive()`）先把记录攒进 `self._pending_calls`，Harness 之后单独调 `drain_calls()` 取走并清空。这是"生产/消费分离、靠可变状态搭桥"的设计。文档明确指出：

> 这个设计本身就是 bug 的温床——缓冲区什么时候清、被谁清，两个方向都能错。

具体隐患：`_perceive()` 可能被 `reset()`/`observe()`/`step()` 多处共用地间接调用（当时还有 `inspect()`），如果 `drain_calls()` 被调用的时机和产生记录的时机没对齐（比如两次 `_perceive()` 之间忘了 drain，或者 drain 早了漏了后一次的记录，或者 drain 晚了把不该属于这次调用的旧记录也带出去），trace 里的账就会算错，而这种错误往往很难在测试里稳定复现。

**新方案（`calls` 跟着返回值走）**：`_perceive()` 直接返回 `(ScreenState, TerrainMap, calls)` 三元组，调用记录**作为返回值的一部分直接交出去，不再攒进实例状态**。谁调用了 `_perceive()`，`calls` 就跟着这次调用的返回值一路原样向上传：

```
_perceive() → observe() → reset()
_perceive() → observe() → step()（经由 ToolResult.calls）
```

`step()` 里体现得最清楚：它调 `self.observe()`，把拿到的 `result.calls` 原样挂在已经存在的 `ToolResult` 上——不必新开一个类型，也不必记得在某个时机去 drain。

**这个方案的优点**：
- 不需要任何跨调用的可变状态，也就不存在"谁来得早谁来得晚"的记账错位问题。
- `calls` 的正确性由普通的函数返回值传递保证，不依赖"记得在正确的时机去 drain"这种容易遗忘的操作序。
- 不产生模型调用的世界（假设的其他 `WorldPort` 实现）只需返回空列表即可满足契约，这不是负担。

一句话回答"为什么需要 `_pending_calls`"这个问题本身：**其实并不需要**——它是旧设计遗留的产物，用来解决"感知开销要进 trace 但不能进 Observation"这个真问题，但选择的手段（跨调用可变缓冲区 + 显式 drain）引入了比它解决的问题更多的错误可能性，因此被替换为"让 `calls` 随返回值自然向上传播"的现方案。

---

## 6. 其他内部细节速查

- **`_status_line(s: ScreenState) -> str`**（结果进 `Observation.status`；函数和字段都曾叫 `summary`，改名是因为它是**一句状态**，不是对这一帧的概括）：给大脑读的极简自然语言状态，只是 prompt 的上下文开头，详细字段都在 `facts` 里。按 `Scene` 枚举给一句"你在……"的话，再视 `overlay` 追加对话框摘录或选项列表。
- **`parse_screen(text)`**：把模型原始文本解析为 `ScreenState`，容忍 ` ```json ` 包裹（模型最常见的格式偏差），其余解析失败一律返回 `None`，不做其它兜底。
- **`_tick(frames)`**：逐帧调用 `self._pyboy.tick(1)`，不是批量 `tick(n)`——因为 `tick(n)` 只在最后限速一次，批量调用在 `watch` 模式下画面会一跳一跳，逐帧才平滑；无头模式不限速，逐帧的额外开销可忽略。若某次 `tick(1)` 返回假值（窗口被关），置 `self._closed = True` 并立即返回——这是 world 唯一的终止权。
- **`PRESS_FRAMES=10`**（按键按住的帧数）、**`WITHIN_ACTION_FRAMES=120`**（链上每按一次之后推进多少帧）、**`AFTER_ACTION_FRAMES=360`**（整条链跑完后再推进多少帧才感知）、**`BOOT_FRAMES=600`**（无存档时空转越过开机 logo）。
- **导入期防护性断言**：模块顶层有一条 `assert`，检查 `OVERLAY_ACTIONS`（定义在 `schemas/observation.py`，掩码表）里出现的每个键都在 `ALL_BUTTONS` 里。这条**在导入时查，不留给测试**：两张表分处 `schemas` 和 `world` 两个文件，改了一边忘了另一边时，harness 会交出一个世界不认识的动作，而错误要等到大脑选中它、`step()` 真正执行时才会炸——离病因隔了三层，导入期断言把这类错误提前到进程启动那一刻。
- **`stop()`**：`self._pyboy.stop()`，非 `WorldPort` 协议方法，是资源释放的收尾。
