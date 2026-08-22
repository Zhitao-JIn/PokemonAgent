# `schemas` 模块技术规格

本文档覆盖 `pokemon_agent/schemas/` 下六个文件：`task.py`、`observation.py`、`action.py`、`memory_episodic.py`、`memory_semantic.py`、`trace.py`。

---

## 0. 模块定位

### 0.1 "跨层契约" vs 模块内部类型

这六个文件里的每个模块 docstring 开头都会标注该文件是不是"跨层"的，这是整个 `schemas` 目录的组织原则：

- **跨层类型**：出现在 `interfaces/`（`WorldPort`、`GameToolPort`、`BrainPort`、`MemoryToolPort`、`TracePort` 等 Protocol）的方法签名里的类型。它们是不同层（world、tool、brain、memory、harness/trace）之间真正传递数据的契约，必须放在一个所有层都能 import 的公共位置，否则各层各自定义会导致契约漂移。
  - `task.py` 整个文件都是跨层的（`Task` 出现在 `WorldPort.reset()`/`GameToolPort.reset()`）。
  - `observation.py` 里只有 `Observation`/`Place`/`Landmark` 跨层（出现在 `WorldPort`/`GameToolPort` 签名里）；`Scene`/`Overlay`/`ScreenState`/`TerrainMap` 及以下**不跨层**，是 `PyBoyWorld` 内部把一帧画面解析成结构化状态、再压成 `Observation.facts` 里字符串的中间产物，**大脑不该碰**。文件注释明确说这条边界"现在只能靠人守"——历史上曾靠 `react.py` 只 import `core` 强制，合并/拆分模块之后这层强制力已经不存在，只剩纪律约束。
  - `action.py` 整个文件跨层，出现在 `GameToolPort`/`BrainPort` 签名里。
  - `memory_episodic.py`（`MemoryEntry`/`Snapshot`）不跨层描述未见于文件顶部，但其 import 只被记忆子系统内部使用；作用域是"一次经过"的经验。
  - `memory_semantic.py` 的 `ObjectFact` **"跨层，但只跨这一小段"**：从不出现在 `WorldPort`/`GameToolPort` 签名里，只出现在 `MemoryToolPort`；大脑看不到 `ObjectFact` 这个类型本身，只看到 `known_objects` 里渲染出的一段文字。
  - `trace.py` 里 `ModelCall`/`Decision`/`Verdict` 出现在 `BrainPort` 签名里，`TraceEvent` 出现在 `TracePort` 签名里，均跨层。

一句话总结这个分层原则：**跨层类型是不同子系统之间唯一被允许交换的数据形状；模块内部类型只在产生它的那个子系统内部流动，最终都要被"压平"成跨层类型能装下的形式（通常是字符串）交给下一层。**

### 0.2 为什么原来的 `core.py` 拆成六个文件

拆分依据是"契约管的是哪件事"，而不是技术上的字段分组：

| 文件 | 划分依据 |
|---|---|
| `task.py` | 任务契约——一次尝试（episode）的成败判据与边界 |
| `observation.py` | 感知契约——大脑在某一步看到的世界是什么样，以及"一帧画面怎么被解析成这个样子" |
| `action.py` | 动作契约——大脑能做什么、选出来的一步长什么样 |
| `memory_episodic.py` | 情景记忆契约——"我在那种画面里选了什么、结果如何"，作用域是一次经过、有时效 |
| `memory_semantic.py` | 语义记忆契约——"世界是什么样"，自带作用域、域内恒真 |
| `trace.py` | Trace 契约——记账、判定结果、事件流 |

`observation.py` 内部虽然又分成"跨层的感知结果"（`Observation`/`Place`/`Landmark`）和"不跨层的画面解析中间产物"（`Scene`/`Overlay`/`ScreenState`/`TerrainMap`），但没有进一步拆成两个文件，理由是文件 docstring 明说的：**它们是同一件事的两个阶段**——"世界被感知成什么结构"和"结构怎么变成大脑看到的那份 `Observation`"——拆成两个文件反而要在中间加一层 import 才能看出这层因果关系，得不偿失。

`memory_episodic.py` 与 `memory_semantic.py` 分成两个文件，是因为二者是本质不同的两类记忆，文件顶部各自都强调"不要与另一类混淆"：情景记忆答"我做了什么、结果如何"（有时效，取回靠画面相似）；语义记忆答"世界是什么样"（自带作用域、域内恒真，不会过期）。混在一个文件/一个模型里会把"这一格给了什么"和"水克火"这类不挂坐标的知识混进同一张表。

### 0.3 文件间依赖关系

```
observation.py   (无对本模块内其他文件的依赖)
      ↑
      │ from .observation import Observation
action.py
      ↑
      │ from .action import Action
trace.py

memory_episodic.py  → from .observation import Observation
memory_semantic.py  → from .observation import KIND_DOOR, Landmark

task.py  (无对本模块内其他文件的依赖)
```

即：`observation.py` 是全模块的地基（`Place`/`Landmark`/`Observation` 被 `action.py`、`memory_episodic.py`、`memory_semantic.py` 复用）；`action.py` 依赖 `observation.py`；`trace.py` 依赖 `action.py`（间接依赖 `observation.py`）；`task.py` 完全独立；`memory_episodic.py` 与 `memory_semantic.py` 都只依赖 `observation.py`，二者互不依赖。

---

## 1. `task.py`

### `Task`（跨层，出现在 `WorldPort.reset()` / `GameToolPort.reset()` 签名里）

一个有明确成败判据的任务；**episode 的边界就是任务的边界**。

| 字段 | 类型 | 默认值 | 约束/说明 |
|---|---|---|---|
| `task_id` | `str` | 无默认，必填 | 任务标识，同一任务的多次尝试共用它 |
| `goal` | `str` | 必填 | 给 LLM 读的目标描述，会进 prompt |
| `success_criteria` | `str` | 必填 | 成败判据的人类可读描述；**判定由 world 实现**，本类只存描述文本 |
| `max_steps` | `int` | 必填 | 步数上限，超出即判失败，应 > 0（文档说明，非 Pydantic 校验强制） |

**设计理由**：为什么用"任务"而不是"通关"作为 episode 边界——通关是几千步、只产出一个 0/1 结果，机制三（蒙特卡洛回填）的折扣一路乘下去，回填到前期步骤上几乎是噪声；评测也只能报"通关了没有"这一个二值数字。任务级颗粒度则能报成功率、失败模式分布、有记忆 vs 无记忆的对比。但任务有下界：必须长到单靠上下文装不下、必须跨任务复用经验才做得好，否则记忆架构失去存在理由（例：合适的粒度是"打赢二号道馆"，不合适的是"和 NPC 说句话"）。

---

## 2. `observation.py`

本文件分两部分：上半部分（`Place`/`Landmark`/`Observation`/`PerceptionResult`）跨层，是大脑真正看到的东西；下半部分（`Scene` 及以后）不跨层，是 `PyBoyWorld` 把一帧画面解析成结构化状态的中间物，一次都不出现在 `interfaces/` 签名里。

### 2.1 常量：`BUTTON_FACING: dict[str, str]`

`{"up":"north","down":"south","left":"west","right":"east"}`。方向键到朝向的映射。

**设计理由**：朝向是"我们自己的动作推出来的，不是看出来的"。宝可梦里按方向键撞墙时人也会转向（只是不移动），所以"按过 up"就等价于"面朝北"，没有例外；实测让 VLM 读朝向是 8 步 8 次全错。该表放在 `observation.py` 而不是 `world` 层，是因为 world（更新 `facing`）和工具层（计算这一步走的是哪个方向）两处都要用同一张表，必须共享单一定义。

### 2.2 常量：`FACING_STEP: dict[str, tuple[int, int]]`

`{"north":(0,-1),"south":(0,1),"west":(-1,0),"east":(1,0)}`。朝向到全局坐标位移。y 向下增大，与 `walk_map` 行号一致。

**设计理由**：`a` 键作用在角色面朝的那一格上，需要这张表算出"这一步刚才在跟谁互动"。

### 2.3 常量：`INTERACT_KEY = "a"`

**设计理由**：`a` 作用在面朝的那一格（对人说话、看招牌、进门），这是游戏规则不是策略，因此放进 schemas 而不是策略代码。放在这里（而非工具层）的理由与 `BUTTON_FACING` 相同：工具层用它判断"这一步是不是在互动"，world 用它把连续按键夹成一次（因为 `a` 键收益全在中间那几帧，连按会把它们整个吃掉）。若两处各写一次字面量 `"a"` 不会报错，但会在有人改动时静默分叉。

### 2.4 常量：`KIND_DOOR, KIND_SIGN, KIND_PERSON = "门", "招牌", "人"`

地标（`Landmark.kind`）的三种类型取值。

**设计理由**：与下半部分地图字符集里的 `DOOR/SIGN/PERSON = "D"/"S"/"N"` 是两组完全不同的名字空间——这两组名字曾经撞过一次，症状是"门"分支静默不生效，因此文档特别强调二者不是一回事。

### 2.5 `Place`（跨层）

地图上一个格子，**全项目唯一的"位置"表示**。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `map_id` | `int` | 必填 | 地图编号 |
| `x` | `int` | 必填 | 全局 X 坐标 |
| `y` | `int` | 必填 | 全局 Y 坐标 |

方法：
- `step_toward(facing) -> Place`：面朝 `facing` 时 `a` 键会作用到的那一格（用 `FACING_STEP` 计算）。
- `key: str`（property）：`"{map_id}:{x}:{y}"`，**记忆的键，跨 episode 稳定**。
- `render() -> str`：渲染成 `"全局坐标 地图{map_id} x={x} y={y}"`，**不用括号写法**（括号写法留给屏幕格，用以在字面上区分全局坐标与屏幕相对坐标）。

**设计理由**：做成模型而不是三个散字段，是因为它现在承载记忆的键——语义记忆按 `(map_id, x, y)` 索引，三个数必须整体传递、整体比较；若散着传，迟早会漏掉 `map_id`，漏掉后两张地图上相同坐标会相撞，而这种错误不报错，只会让记忆开始张冠李戴。

### 2.6 `Landmark`（跨层）

屏幕上一个值得记住的东西：门/招牌/人。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `kind` | `str` | 必填 | "门 / 招牌 / 人" |
| `place` | `Place` | 必填 | 位置 |

方法：`render() -> str`，`"{kind} x={x} y={y}"`。

**设计理由**：**没有名字字段**。名字（这是谁家、招牌写什么）在总览画面里没有可观测证据，只能靠走过去交互后记住——这正是语义记忆（`ObjectFact`）该做的事，不属于感知层。

### 2.7 `Observation`（跨层）

大脑在某一步看到的世界。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `step` | `int` | 必填 | 本 episode 内第几步，从 0 开始 |
| `place` | `Place \| None` | `None` | 主角所在格子的结构化表示；`facts["where"]` 是它渲染给模型看的文本，记忆键要用这三个数直接算，不能反解字符串 |
| `summary` | `str` | 必填 | 给 LLM 读的自然语言状态描述 |
| `facts` | `dict[str, str]` | `{}` | 结构化状态字段（位置、HP、道具等）；机制一的 state key 未来从这里派生 |
| `done` | `bool` | `False` | episode 是否已终止 |
| `success` | `bool` | `False` | 任务是否达成，**只在 `done=True` 时有意义**，否则恒为 False |

**设计理由**：只放"大脑决策需要的"信息。原始画面、模拟器内部状态不进这里——那些属于 harness，大脑看不到也不该看到。

### 2.8 `PerceptionResult`（跨层）

一次感知动作（`perceive`/`inspect`/`reset`）的结果：观测 + 这次调用产生的模型调用记录。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `observation` | `Observation` | 必填 | 感知结果 |
| `calls` | `list[dict[str, str]]` | `[]` | 每条模型调用记录，按发生顺序；至少含 `input_tokens`/`output_tokens`/`latency_ms`/`attempt`/`ok`，建议附 `raw`。**空列表表示命中缓存，不是 None**——调用方不用先判空 |

**设计理由**：
- `calls` 不放进 `Observation` 内部：`Observation` 是"大脑看的东西"，大脑不该知道 token 数、延迟这类记账信息；放进去就是把跨层契约当日志用。但这份账又必须原样传给 Harness 写 trace，所以让它跟 `Observation` 平行挂在这层薄包装上。
- **曾经有一个 `drain_calls()`**：早期版本把调用记录攒进私有实例变量 `_pending_calls`，靠 `reset`/`perceive`/`inspect` 共用的产账方法写入，再由 Harness 单独调用 `drain_calls()` 取出。这种"生产和消费分离、靠可变状态搭桥"的设计本身是坑：缓冲区"什么时候清空"无论早了晚了都会把账算错。真正的修法是让产生调用记录的地方直接把它当返回值交出来，一路跟着 `_perceive()` → `observe()` → `reset()`/`perceive()`/`inspect()` 普通地往上传，不需要缓冲区，也就不存在"漏记账"或"记重账"这类依赖时机的 bug。

### 2.9 `Scene`（`str, Enum`，不跨层）

"你在什么场合"，决定要读哪些字段。取值：`FIELD`（野外）、`INDOOR`（室内）、`BATTLE`（战斗）、`MENU`（系统菜单）、`SHOP`（商店）、`TRANSITION`（过场）。

**校验/约束**：文件顶部声明 `Scene`/`Overlay` 受 **append-only 约束**——机制三的 `(state-key, action) -> value` 一旦开始积累，枚举值只能增不能改（否则历史记录中的 key 会错位）。

### 2.10 `Overlay`（`str, Enum`，不跨层）

"屏幕上盖着什么等你操作"，决定可以按什么键。取值：`NONE`（无弹层）、`DIALOG`（对话框）、`CHOICE`（选择框）。同样受 append-only 约束。

### 2.11 常量：`OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]]`

- `NONE` → `("up","down","left","right","a","start")`
- `DIALOG` → `("a",)`（方向键无效，只能推进）
- `CHOICE` → `("up","down","a","b")`（移光标/确认/取消）

**设计理由**：动作掩码**只看 overlay，与 scene 无关**。这是把动作可用性拆成"场合(Scene) × 叠加层(Overlay)"二元组、而不是每个组合单独定义规则的直接回报——三条规则即可覆盖所有场合。

### 2.12 常量：`SCENE_FIELDS: dict[Scene, tuple[str, ...]]`

- `FIELD: ()`、`INDOOR: ()` —— 无字段
- `BATTLE: ("my_name","my_level","my_hp","foe_name","foe_level","foe_hp")`——`my_hp` 是 `当前/最大` 数字（我方状态框右下角有数字 HP）；`foe_hp` 没有数字可抄，填血条挡位（满/较高/过半/较低/危险），因为 Gen1 原版对手状态框只有一条血条，没有 `当前/最大` 这种数字——两个字段格式不一样是画面本身决定的，不是遗漏（见 `prompts/perceive_screen.md` 第二节）
- `MENU: ("title",)`
- `SHOP: ("money","items")`
- `TRANSITION: ()`

**设计理由**：
- 野外/室内没有 `fields`：地形来自模拟器内存（`world/ram.py`），语义来自 `overview` 和 `landmarks`。曾经这里放过 `facing, north, south, east, west, landmarks`，实测全是噪声——例如 `north: grass ×3` 在主角连走六步过程中一字未变，说明它不是位置的函数，而是"这张图上半部分是草"的函数；字段名承诺"测量"，VLM 交付的是"描述"，两者差一个数量级，不是靠改 prompt 能弥合的。`facing` 更不该问模型：朝向就是最后一次按的方向键，world 自己知道，是确定量，问模型等于把已知量换成一个 8/8 全错的猜测（参见 `BUTTON_FACING`）。
- `SCENE_FIELDS` **是数据不是类型**：给某个 scene 加字段不改变任何枚举值，不触发 append-only 约束。字段名进 prompt 告诉 VLM 该填什么，填出来的值进 `ScreenState.fields`。

### 2.13 常量：`GRID_COLS, GRID_ROWS = 10, 9`

屏幕格数（160/16=10，144/16=9）。

### 2.14 常量：`PLAYER_CELL = (4, 4)`

主角在屏幕上的格子坐标，是常量。

**设计理由**：宝可梦红的镜头锁死在主角身上，主角在屏幕上的位置永远不变（28 张真实截图验证，野外/室内/有无对话框均无例外）。这把感知任务降了一维：模型不需要定位主角，只需要读格子内容；同时提供免费的自检位——模型把 `@` 放到别处，说明它的坐标系整个是错的，这一帧可判废重试，不必等 agent 撞墙才发现。

### 2.15 常量：`PLAYER_MARK="@"`、`WALKABLE="."`、`BLOCKED="#"`、`DOOR="D"`、`SIGN="S"`、`PERSON="N"`、`GRASS="G"`

地图字符集常量（与 `KIND_DOOR`/`KIND_SIGN`/`KIND_PERSON` 是两套独立名字空间，见 2.4）。

### 2.16 常量：`TERRAIN_MEANING: dict[str, str]`

地形符号含义映射表（`.`/`G`/`D`/`S`/`N`/`#`/`@`）。

**设计理由**：每一个符号都来自模拟器内存查表，没有一个是"认"出来的：`.`/`#` 查 tileset 可通行表（游戏自己的 `CheckTilePassable`）；`G` 来自 tileset 头的 `wGrassTile`；`D` 来自地图头 warp 表（还带目标地图）；`S` 来自地图头 sign 表；`N` 来自精灵表 `wSpriteStateData1`；`@` 是常量。这是这一版与前三版的根本差别：视觉模型反复读错的东西（墙认成门、窗户认成人），在这个设计里根本不存在"认"这个动作。该 dict 同时是 `terrain_legend()` 渲染 prompt 图例的数据源，两边共用一份，避免各写一份导致漂移（模型和大脑用两套字典这种错不会报错，只会静默互相误解）。

### 2.17 常量：`MAP_CHARS = frozenset(TERRAIN_MEANING)`

合法地图字符集合，供 `TerrainMap._check_shape` 校验用。

### 2.18 函数：`terrain_legend() -> str`

把 `TERRAIN_MEANING` 渲染成 prompt/动作说明里的图例（逐条 `` - `ch` text ``）。

### 2.19 `TerrainMap`（不跨层）

从模拟器内存读出的通行图，**不是识别出来的**。

| 字段 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `cells` | `list[str]` | 必填 | `GRID_ROWS` 行、每行 `GRID_COLS` 个字符，取自 `MAP_CHARS` |
| `map_id` | `int` | 必填 | 当前地图编号（`wCurMap`） |
| `player_x` | `int` | 必填 | 主角地图内 X 格坐标（`wXCoord`） |
| `player_y` | `int` | 必填 | 主角地图内 Y 格坐标（`wYCoord`） |
| `ambiguous_cells` | `int` | `0` | 有多少格子的四个 8x8 子 tile 通行性不一致；采样规则的健康指标，实测 90 格中仅 1 格（门）不一致 |

**校验逻辑**：`field_validator("cells")` `_check_shape`——检查行数是否等于 `GRID_ROWS`，每行长度是否等于 `GRID_COLS`，字符是否都在 `MAP_CHARS` 内，任一不满足抛 `ValueError`。**理由**：内存读出的东西形状不对，说明地址或换算错了；若强行补齐，会把一个地址 bug 伪装成一张残缺的地图，掩盖真实错误。

方法：
- `at(col, row) -> str`：取某格字符。
- `neighbors() -> dict[str, str]`：四个方向键各自通往哪一格；单独成方法是因为这四格和其余 86 格不是一回事——它们决定这一步能不能动。
- `render() -> str`：渲染成带行号（无列号）的文本，行号即全局 y 坐标；**详细设计理由见下**。
- `landmarks() -> list[Landmark]`：屏幕上的门/招牌/人换算成全局坐标；**详细设计理由见下**。
- `place() -> Place`：主角所在格子。
- `render_neighbors() -> str`：四邻渲染成一行中文（北/南/西/东）。
- `render_landmarks() -> str`：`landmarks()` 渲染成一行，供进 `facts`。

**`render()` 关键设计理由（全局坐标 vs 屏幕格）**：
- 行号写全局坐标（`y=...`），**不给列号**，是刻意选择。曾经用的是屏幕格坐标（`0-9`/`0-8`），导致同一张图上并存两套坐标系——地图渲染用屏幕格，`where`/`landmarks`/`known_objects` 用全局坐标，中间隔一次换算。这次换算被认定为**全项目最大的错误来源，且是自造的**：决策模型每步花一千多输出 token 反复核对同一行字符仍会推错（例如把 `(6,4)` 当作不可达，实际是可走的 `G`）；把换算结果写进子目标（"移动到屏幕格(7,4)"）导致判据永远无法成立（走过去后主角在屏幕上仍是 `(4,4)`）；判定器拿到该判据又会把全局坐标误读成屏幕坐标。删掉换算后这三类错误一起消失，图上数字与记忆中数字变成同一套坐标，无需转换即可对齐。
- 没有列号是因为全局 x 是两三位数，一列只有一个字符宽，横着写不下；曾尝试把列号竖着拆成十位/个位两行，模型读不动（要求纵向拼数字，比原换算还难）。因此只在开头写一句"这一屏覆盖到哪"。这个代价被认为是零，因为模型本不该在图上数格子找东西——门/招牌/人的精确坐标已由 `landmarks`/`known_objects` 提供，四邻已由 `neighbors` 算好，地图剩下的用途只是"看形状"（走不走得通、哪边死路），看形状不需要列号。
- 格子间不加空格：曾用空格分隔排版整齐，实测模型把空格也当成格子，一行 10 格看成 19 格，坐标全线错位。

**`landmarks()` 关键设计理由（全局坐标 + 无名字）**：
- 换算为全局坐标：地标是"地图上的一个地点"，跨步骤存在，坐标必须跨步骤成立。曾用屏幕格存储，导致模型取回上一步记忆"民宅的门 (7,7)"，对照当前地图发现 `(7,7)` 是 `#`，花了 2235 个 output token、49 秒试图判断是记忆错了还是地图错了——两边都没错，是数据自相矛盾。换算是纯算术（`全局 = 主角全局坐标 + (屏幕格 - PLAYER_CELL)`），不读额外内存。
- 没有名字：名字在总览画面里没有可观测证据（招牌文字未渲染需按 A 弹框才有，所有门是同一深色矩形）。名字的三个可能来源：内存（warp 表带目标地图编号，精确，但那是"世界怎么连起来"，正是长程记忆要学的东西，白送等于取消这个项目要证明的事）；视觉模型（三轮实测全在编造，例如给真新镇编出并不存在的宝可梦中心招牌，那是先验不是观察）；经验（走进去看见记住，**只有这一个是对的**，属于语义记忆/object 的职责）。所以现在只给类型和位置，名字将来从语义记忆里长出来。

### 2.20 常量：`NEEDS_OVERVIEW = (Scene.FIELD, Scene.INDOOR)`

哪些场合必须给 `overview`。

**设计理由**：只有这两类场合"有布局可言"，`overview` 的作用是在挑细节之前先做一次全局判断，约束后续局部判断。战斗/菜单/商店内容全在 `fields`/`options` 里，那里的 `overview` 是装饰；把它也设为必填只会给无关代码添噪声——文档强调"契约里的每一条约束都应该是有人真的依赖的"。

### 2.21 `ScreenState`（不跨层）

一帧画面解析成的结构化状态。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `scene` | `Scene` | 必填 | |
| `overlay` | `Overlay` | 必填 | |
| `overview` | `str` | `""` | 一句话描述整幅画面布局；**字段声明顺序即模型输出顺序**，必须写在 landmarks 之前 |
| `dialog_text` | `str` | `""` | `overlay=DIALOG` 时框内文字，其他情况为空 |
| `options` | `list[str]` | `[]` | `overlay=CHOICE` 时的选项列表 |
| `cursor` | `int \| None` | `None` | `overlay=CHOICE` 时光标位置，0 起，未知为 None |
| `fields` | `dict[str, str]` | `{}` | 该 scene 的结构化字段，键取自 `SCENE_FIELDS`；读不出的字段直接不放，**不填占位值** |

**设计理由（字段值统一放 `fields` 扁平 dict）**：机制三的 state key 要从 `(scene, overlay, fields)` 均匀派生；若给每个 scene 定单独子模型，key 的构造就要对 scene 分支，得不偿失。

**设计理由（`overview` 必须在 `landmarks` 之前）**：字段的声明顺序就是模型的输出顺序；先说整体会约束后面挑地标的结果，反过来先挑地标再总结，总结就只是复述已经挑错的东西。

**校验逻辑 1**：`model_validator(mode="after")` `_overview_comes_with_a_layout`——若 `scene in NEEDS_OVERVIEW` 且 `overview` 为空（strip 后），抛 `ValueError`。理由：`overview` 不是补充说明，是"看细节之前的那次全局判断"；允许缺失，模型会跳过它直接挑地标，而跳过的正是唯一能牵制局部判断的东西。

**校验逻辑 2**：`field_validator("fields", mode="before")` `_stringify`——把非字符串的字段值规整成字符串：`bool` → `"true"/"false"`；`list/tuple/set` → 排序后用 `", "` 拼接；`None` → 丢弃该键（不留占位）；其余 → `str()`。
理由：实测模型会按语义给类型（`walkable` 给 bool、`nearby` 给 list），内容完全正确却因 `dict[str, str]` 类型限制被整条拒绝，23 帧里 11 帧栽在这上面，且与感知质量无关；判据类比 ```json 代码块包裹这种"常见格式偏差、语义无歧义"的情况，为它判错不划算。不直接放宽成 `dict[str, Any]`，是因为机制一的 state key 要从 `fields` 派生，值类型不统一无法稳定构造 key，因此在入口统一规整一次，下游只见字符串。**列表值排序后再拼接**：模型两次读同一画面可能给出不同顺序的 `nearby`，不排序会让同一状态派生出不同 state key，导致机制三失稳。

方法：
- `available_actions() -> tuple[str, ...]`：`OVERLAY_ACTIONS[self.overlay]`，masking 数据来源。
- `expected_fields() -> tuple[str, ...]`：`SCENE_FIELDS[self.scene]`，用于组 prompt 和标定完整度。

### 2.22 函数：`describe_scene_fields() -> str`

把 `SCENE_FIELDS` 渲染成 prompt 里的字段清单文本。

**设计理由（配套注释）**：prompt 文件里的字段清单和输出样例是手写在 `.md` 文件中的，因为 prompt 文件必须能被完整读到——用 `$scene_fields` 变量替换的话，"prompt 可 review" 就成了空话。漂移交给测试挡（`test_prompts.py` 拿这里的输出与 `.md` 内容对照），而不是牺牲可读性去自动生成。

### 2.23 常量：`EXAMPLES: dict[Scene, ScreenState]`

每个 `Scene` 对应一份合法样例 `ScreenState`，同时作为 prompt 内容基准和测试基准。

**设计理由**：只给一份野外样例时，模型在战斗画面上会照着野外样例的形状填、把地标也编出来——样例是模型唯一能看到的"输出长什么样"的实例，缺哪一类那一类就靠它自己猜。三个样例分别示范容易出错的点：`indoor` 样例中被对话框遮住的三行全部写 `?`（不凭印象补，这是 `?` 唯一高频用途）；`battle` 样例中 `landmarks` 为空（战斗画面没有格子坐标）；`transition` 样例什么都不填（过场是一帧无内容画面，硬填即编造）。prompt 里的样例是手写的（保证文件可读性），本模块里的这份是校验基准，`test_prompts.py` 逐字对照，出现漂移当场失败。

### 2.24 函数：`json_output_examples() -> dict[Scene, str]` / `json_output_example() -> str`

把 `EXAMPLES` 渲染成格式化 JSON 文本；后者返回 `Scene.FIELD` 那一份单例（保留单数形式是因为野外是最主要的一类，测试和文档常单独引用）。

---

## 3. `action.py`

依赖：`from .observation import Observation`。

### 3.1 `Intent`（`str, Enum`，跨层）

大脑这一轮想做哪一类事，是流程图的分派依据。取值：

- `PRESS = "press"`：按键，推进世界，**唯一不可逆的一类**。
- `PUSH_GOAL = "push_goal"`：把子目标压进目标栈，不推进世界。
- `INSPECT = "inspect"`：对同一帧再问视觉模型一个具体问题，不推进世界。**必须带 `focus`**——不带的话等于把同一帧原样再看一遍（`perceive()` 是帧内缓存的，返回字节完全一样，不产生新信息），模型拿不准时一定会选它，下一轮看到同样画面会再选一次；带上具体问题、走另一份 prompt，才真的产出新事实、值那次调用的钱。

**设计理由**：分成三类而不是全塞进按键里，是因为它们代价和后果完全不同——只有 `PRESS` 不可逆推进世界，另两类只改变大脑自己的处境；分开后"花了多少轮想、多少轮走"可以直接从 trace 数出来。做成枚举而非布尔标志的收益：未来加第四类（读记忆、写记忆、调工具）时，只需加一个枚举值加一个图节点，`choose()` 和 prompt 的形状不变。

### 3.2 `Goal`

一个目标：想达成什么，以及怎么算达成。

| 字段 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `goal` | `str` | 必填 | `min_length=1`，想达成什么，一句话 |
| `criteria` | `str` | 必填 | `min_length=1`，画面上出现什么才算达成，**要能只看一帧就判断** |

**设计理由**：两项必须一起给，不能只给目标——判定器的输入就是这两项，没有判据它只能凭"看起来差不多了"判断，那正是成功率被污染的地方。大脑压子目标时必须同时写出判据；写不出判据的子目标本身就说明它没想清楚要什么。

### 3.3 常量：`MAX_RATIONALE = 3`

一个动作最多带几条论据。

**设计理由**：有两个执行点共享这个常量——`Action` 的字段约束（数据契约）和 `Brain._parse`（外部输入校验），必须同源，否则模型给 4 条论据时会出现"解析器放行、构造时报错"的自相矛盾系统。

### 3.4 `Action`（跨层）

大脑选出的一个动作。

| 字段 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `intent` | `Intent` | `Intent.PRESS` | 这一轮做哪类事，分派靠它，`name` 只在 PRESS 时有意义 |
| `name` | `str` | `""` | 按键名，须来自当时的 `ActionSpace`，只在 PRESS 有意义 |
| `args` | `dict[str, str]` | `{}` | 按键参数，目前只有 `times`（连按次数） |
| `goal` | `Goal \| None` | `None` | 要压入目标栈的子目标，只在 PUSH_GOAL 有意义 |
| `focus` | `str` | `""` | 想细看什么，只在 INSPECT 有意义 |
| `thought` | `str` | 必填 | `min_length=1`，选择该动作的完整推理；**只进 trace，不进 memory，不影响后续决策**；不设长度上限 |
| `rationale` | `list[str]` | 必填 | `min_length=1, max_length=MAX_RATIONALE`，最能支持该动作的论据；**进情景记忆** |

**设计理由**：
- `thought`/`rationale`/`name+args` 服务于三个不同消费方，不要合并。`thought` 不设上限，因为它的长度就是模型这一步的算力，压缩它压的是思考本身而不是日志体积。
- 进记忆的是**论据而不是结论**：结论（"所以该捡药水"）可从 `name` 反推，存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）是 `name` 里没有的信息，且论据是"适用条件"——未来取回时可检查它现在是否还成立，结论做不到这一点。
- 论据一律按"有时效"处理，不区分持久与否；持久知识跨 episode 复用属于 skill library（机制二），本阶段不做。

**校验逻辑**：`model_validator(mode="after")` `_fields_must_match_the_intent`：
- `intent=PRESS` 且 `name` 为空 → 报错。
- `intent=PUSH_GOAL` 且 `goal is None` → 报错。
- `intent=INSPECT` 且 `focus.strip()` 为空 → 报错。

理由：每种 intent 必填字段不同，必须在这里挡住，不能漏到分派环节。若漏过去，例如 `push_goal` 缺 `goal` 会在 Harness 里 assert 崩掉——这会把"模型的输出问题"错误地报成"我们自己的契约违约"，排查时看堆栈会指错方向。在这里失败则走 `ParseFailure` 路径，会被重试，也会按失败模式统计。

### 3.5 `ActionSpace`

当前状态下**可用**的动作集合（state-dependent action masking）。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `intents` | `list[Intent]` | `[Intent.PRESS]` | 这一轮允许哪几类 intent；**由 Harness 填**——能否拆子目标取决于目标栈深度，那是循环层面的事，工具层不知道 |
| `names` | `list[str]` | 必填 | 可用按键名，应非空 |
| `descriptions` | `dict[str, str]` | `{}` | 动作名 → 给 LLM 读的说明 |
| `note` | `str` | `""` | 关于整个动作空间的说明（如连按用法），不属于任何单个动作；**必须存在**——prompt 只渲染 `names` 里列出的动作说明，塞进 `descriptions` 的额外条目永远不会被渲染出去 |

方法：`contains(name) -> bool`。

**设计理由**：语义上这不是"全部动作"，是"此刻允许的动作"；动作空间本身不增长，增长的是掩码之外的 skill library（本阶段不做）。

### 3.6 `ToolResult`（跨层）

一次动作执行的结果。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `message` | `str` | `""` | 给 LLM 读的结果描述 |
| `observation` | `Observation \| None` | `None` | 执行后的新观测；None 表示调用方需另行 `perceive()` |
| `calls` | `list[dict[str, str]]` | `[]` | 推进这一步产生的模型调用记录（通常是执行后重新感知那一次）；语义同 `PerceptionResult.calls`：按序排列、失败也计入、空列表表示命中缓存无新调用（不是 None） |

**设计理由（这里曾经有一个 `ok` 字段）**：原含义是"这个动作有没有产生预期效果"（撞墙=False）。在 `PyBoyWorld` 上它被写死成 `True`，因为从像素判断"这一下有没有改变世界"没有便宜可靠的办法（画面自带动画，比对不出因果）。一个恒为真的布尔值比没有更糟——它会出现在事件流和控制台判断分支里，让人误以为那里有信息，实际每条都是 True。要让它诚实唯一的办法是读内存坐标（走没走动），但那是为一个**没有消费方**的字段新增内存依赖。判断动作是否生效本应由前后两次观察对比来回答，而这件事情景记忆层（`MemoryEntry` 两头各存一份完整快照）已经在做，所以选择**删掉而不是补上**。

---

## 4. `memory_episodic.py`

依赖：`from .observation import Observation`。

模块定位：情景记忆答的是"我在那种画面里选了什么、结果如何"，作用域是**一次经过**、取回靠画面相似、**有时效**；不要与语义记忆（答"世界是什么样"，自带作用域、域内恒真）混淆。

### 4.1 常量：`MIN_STITCH = 6`

拼接时至少要重叠几个字符。

**设计理由**：太短会误拼——两句无关的话结尾和开头撞上三五个字符很常见，拼错会以"他说过这句话"的样子进 prompt。Game Boy 一行有十几个字符，重叠通常是整整一行，门槛设高一点几乎不会漏拼。

### 4.2 函数：`_stitch(prev, new) -> str | None`

把滚动窗口读出的下一段文本接到上一句后面，接不上返回 `None`。三种可接情况：`new` 被 `prev` 包含（对话没动）；`prev` 被 `new` 包含（抄得更全）；首尾重叠 ≥ `MIN_STITCH` 个字符（滚了一行）。都不满足则视为"另一句话"，单独占一条。

### 4.3 `Snapshot`

一次观察的快照；与 `Observation.facts` 唯一分歧在于：facts 是"这一帧的全部"，快照是"其中还能拿到、以后要用的那部分"。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `overview` | `str` | `""` | 整体印象，视觉模型给的 |
| `landmarks` | `str` | `""` | 地标，全局坐标（如 `门 x=13 y=5`），来自模拟器内存 |
| `neighbors` | `str` | `""` | 四邻各是什么（如 `北 G 南 . 西 # 东 .`），**相对"我"、不依赖屏幕原点**，跨步骤成立 |
| `position` | `str` | `""` | `全局坐标 地图0 x=10 y=2`，刻意不用括号写法 |
| `dialog` | `str` | `""` | 对话框文字，跨步骤成立（说过就是说过了） |

**设计理由（为什么 `walk_map`/整张地图不在快照里）**：整张图天生是**屏幕相对**的，原点跟着人走，走一步同一个 `(7,7)` 就指向另一块地方；`MAP_HINT` 里明文写着屏幕格"不能跨步骤引用"，但早先版本把整张图和带屏幕格的地标一起存进记忆、下一步又喂回去。实测代价：模型取回上一步记忆「民宅的门 (7,7)」，对照当前地图发现 `(7,7)` 是 `#`，花了 2235 个 output token、49 秒反复重数字符串试图判断是记忆错还是地图错——两边都没错，是数据自相矛盾。真正靠得住的是 `position`（全局坐标）和 `neighbors`（相对"我"的四邻）：撞墙 → 前后 `position` 一模一样；进门 → `position` 里地图编号变了；"我以为西边能走" → `neighbors["left"]` 记录了当时的真实情况。四邻相对"我"、不依赖屏幕原点，因此跨步骤永远成立；整张图能多提供的只是"当时周围的形状"，而这个信息没有稳定坐标系可承载，所以不存。

方法：
- `of(cls, obs: Observation) -> Snapshot`（classmethod）：从 `Observation.facts` 抽字段构造快照，**只抽不加工**——加工过的快照和当时看到的就不是一回事了。
- `render(indent="  ") -> str`：按位置/四邻/对话/概况/地标顺序渲染非空字段。
- `same_place_as(other) -> bool`：仅比较 `position`/`neighbors`/`dialog` 三项是否全同，来判断"完全没有区别"。

**校验逻辑说明（`same_place_as` 为什么不比较全部字段）**：`overview` 是模型每次重写的自然语言，同一帧也可能措辞不同（实测同一 frame sha 下出现过三种不同措辞），用它比较会把"没变"误判成"变了"。

### 4.4 `MemoryEntry`

一条情景记忆：**我看到这样的画面，因为这些理由，做了这个动作，然后变成了这样**。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `before` | `Snapshot` | 必填 | 做决定时看到的画面 |
| `rationale` | `list[str]` | 必填 | 当时的理由；**不是完整推理**，那留在 trace 里 |
| `action` | `str` | 必填 | 选了什么，含连按次数，如 `right ×2` |
| `after` | `Snapshot` | 必填 | 执行之后的画面；结果本身也是一次观察 |
| `key` | `str` | 必填 | 检索键；本阶段用位置占位，机制一接入后换成状态抽象的语义 key |
| `step` | `int` | 必填 | 写入时所处步数 |
| `episode_id` | `str` | 必填 | 这条经验来自哪次尝试 |

**设计理由（为什么两头都是完整观察）**：只记"结果：你在野外"这类一句话，等于把结果压成没有信息量的标签（上一版就是如此，取回十条内容全长一个样）。结果本身也是一次观察，只有完整记下才能回答"那一下到底改变了什么"。代价是相邻两条记录的 `after`/`before` 内容重复，这是有意接受的取舍：**每条自成一体**，取回时不需要拼接上下文、也不依赖其他条目是否还存在。

**设计理由（`(episode_id, step)` 作为坐标，而不是 trace 的 `event_id`）**：`event_id` 是记录格式的产物，取决于这一步之间穿插了多少其他事件，换个记录粒度就会变；`step` 是"轨迹坐标"，机制三沿轨迹回填折扣正是按 step 走的，用它回填时不需要任何转换。

**设计理由（仍只是 episodic，不要与语义记忆/目标混淆）**：这里记的是"这次尝试里发生了什么"，是自己跑出来的轨迹，有时效。语义记忆答的是"世界是什么样"（例如"水克火""map 0 的 (5,5) 通往 map 37"），自带作用域、域内永远为真。目标有完成态，凡有完成态的都不是知识，属于运行时状态，不进这里。程序记忆、skill library（机制二）、值回填（机制三）尚未实现。

方法：`render(reason=True) -> str`：
- `because` 由 `rationale` 用"；"拼接，空则显示"（未给出理由）"。
- `after` 若与 `before` `same_place_as` 为真，显式渲染为"**什么都没变**（位置、四邻、对话框全部相同——这个动作没有效果）"，而不是留给读者自行比较两份快照。
- `reason=False` 去掉"因为"那一行，只留发生过的事；判定器使用该模式。

**关键设计理由**：
1. 渲染文本同时用于"进 prompt 的样子"和"检索打分"，两处共用一份，是为了保证"被选中的理由"和"看到的内容"是同一个东西，避免"按 A 内容选中、却把 B 内容喂进去"且不报错的问题。
2. "什么都没发生"必须显式说明、不能让模型自己去比较：实测模型不会自己比对——连着三步对空地按 `a`，每步都取回上一步"按 a 没变化"的记忆，然后照着自己上一步"站在门格上按 a 是标准操作"的错误结论再按一次，把过去的 `rationale` 当成权威，而那权威恰恰是错的。判定是纯比较，程序做得又快又准，不该留给模型判断。
3. `render(reason=False)` 供判定器使用：判定器需要历史（证据可能出现在几步前），但绝不能读到决策者自己的理由——`rationale` 是被评价者自己的说辞，一旦进入判定器上下文，成功率就会变成决策者自己发给自己的奖状；画面、动作、结果是"发生过的事"，理由是"它对那件事的主张"，两者必须分开。

---

## 5. `memory_semantic.py`

依赖：`from .observation import KIND_DOOR, Landmark`。

模块定位：语义记忆答"世界是什么样，域内恒真"。目前只有一类：**object**——某一格上的东西（门/招牌/人），跟它互动会得到什么。未来加别的类别（如属性克制表）时应各自建模型，不要都塞进 `ObjectFact`——那会把"这一格给了什么"和"水克火"这种不挂坐标的知识混进同一张表。

命名说明：`ObjectFact` 是 `ObjectNote` 改的名字。`ObjectNote`（"记了一笔"）只表达了"这次交互记了什么"的临时想法；搬进语义记忆层之后身份更明确——它是语义记忆里"object"这一类事实的存储形状，`memory/port.py` 的协议、`memory/semantic/object_store.py` 的实现读写的都是这个类型。`ObjectFact` 这个名字为未来"从 attempts 里学出跨对象规律"（如"这类地形的门都要从北边推"）这种更泛化的用途留了空间，`ObjectNote` 没有。

跨层范围：`ObjectFact` **从不出现在 `WorldPort`/`GameToolPort` 签名里**，只出现在 `MemoryToolPort`——大脑不该知道"语义记忆""ObjectFact"这些词，它看到的只是 `known_objects` 里的一段渲染文字。

### 5.1 常量：`RESULT_NONE = "无效果"` / `RESULT_DIALOG = "对话"` / `RESULT_WARP_PREFIX = "进入新地图"`

固定结果集合，只有这三种。

**设计理由**：早一版为门专门区分"没换图"/"没动"，为人/招牌区分"没反应"/"没出现文字"，四种叫法说的其实是同一件事："这次按键没起作用"，合并成 `RESULT_NONE` 一种可省去模型学两套近义词的成本。判"这扇门开没开"就靠结果是否以 `RESULT_WARP_PREFIX` 开头，所以这个前缀只能有一处定义。

### 5.2 常量：`MAX_TRIED = 8`

一个对象最多记几条尝试记录。

**设计理由**：一扇门总共只有 8 种碰法——站在门上按 4 个方向 + 从 4 个相邻格推 1 个方向 = 8，这是坐标几何决定的穷尽上限，不需要另建词汇表。**试过的不淘汰**：超过上限丢最早一条，但同一个 `(坐标, 按键)` 再试一次只会覆盖旧值、不占新名额，正常情况下 8 条足以覆盖全部碰法。

### 5.3 常量：`MAX_OBJECT_LINES = 4`

一个对象最多记几句台词。

**设计理由**：上限不是怕占内存，是怕 prompt——这些条目每帧都要发，一个 NPC 剧情推进中可能说几十句，只留最近几句够用，要点是"这是谁"而不是复述完整台词。

### 5.4 `ObjectFact`

语义记忆（object）的存储形状：某一格上的东西，跟它互动会得到什么。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `landmark` | `Landmark` | 必填 | 该对象的类型与位置 |
| `seen` | `int` | `0` | 进过几次视野；一步最多加一次 |
| `touched` | `int` | `0` | 互动过几次（按 a、或走进这扇门） |
| `first_seen` | `str` | `""` | 第一次见到的时刻，形如 `ep0#3` |
| `last_seen` | `str` | `""` | 最近一次见到的时刻 |
| `lines` | `list[str]` | `[]` | 互动时出现过的文本，按首次出现顺序，去重 |
| `attempts` | `dict[str, str]` | `{}` | `"x=.. y=..→按键"` → 结果，见下 |

**顶层设计理由（与情景记忆的区别）**：情景记忆记的是"我在那种画面里选了什么、结果如何"，作用域是一次经过，取回靠画面相似。`ObjectFact` 记的是"地图39 x=2 y=3 那个人会说什么"，作用域是那一格本身，在该作用域内永远为真，且该作用域会反复出现（下一步、下一局、下周）——这正是长期记忆的范式：自带作用域 + 域内恒真 + 域会再现。

**它解决的具体问题**：实测中 agent 走进 NPC 家对着一个人连按 `a`，在情景记忆的 `rationale` 里凭空断言"确认为母亲"；这句断言进了情景记忆，下一步被取回后模型照着自己的断言又按一次，如此循环。判定器每一步都在纠正这个错误身份，但判定器的话到不了决策模型手里（这条隔离是有意的：让被评价者看见评价者的理由，它会开始朝评价者的措辞优化）。有了 `ObjectFact`，下次站在同一格前，`known_objects` 直接写着那个人说过什么，不需要再猜或再按一次。

**为什么"怎么碰它"（`attempts`）不按类型分字段**：门/坡/其他交互物看似三类东西，实际上只差两维——我人在它旁边还是站在它上面、按的哪个方向。所以不给"门"加 `how`、给"坡"加 `one_way` 这类字段（那些是结论，只能靠模型断言或写死规则，而项目里凡靠断言进记忆的东西最终都会被当成事实反复使用）。存的是 `attempts`：姿势→结果，两边都由 `place` 相减算出，可证伪，不需要预先知道有几种类型。

**通行性归内存、方向性归记忆**："这一格能不能站"永远不进 `ObjectFact`——`walk_map` 每帧从内存现算，属于低层控制，不该由长期记忆猜测。但 `walk_map` 只答"能不能站"，答不了方向（从北边能跳下坡、从南边跳不上来，问的是同一格）；有方向的那一半才是 `ObjectFact` 的职责。

`attempts` 字段细节：键是"按键那一刻角色自己的坐标 + 按了哪个键"，**不翻译成中文姿势**——角色坐标和对象坐标一比就知道是站在上面还是从哪边推；值只有 `RESULT_NONE`/`RESULT_DIALOG`/`RESULT_WARP_PREFIX{map_id}` 三种，都是算出来的：键来自按键那一刻的 `before.place`，值来自 `before.place` 与 `after.place` 相减、或 `after` 是否出现新对话文字。

方法：
- `leads_to: int | None`（property）：门通往哪张地图，没打开过为 `None`。**不是存下来的字段，是从 `attempts` 扫算出来的**——省去"两处真相"（独立字段与 `attempts` 里对应条目万一对不上）的问题；扫 `attempts` 里第一条以 `RESULT_WARP_PREFIX` 开头的结果并取其地图编号。
- `record(key_desc, result) -> None`：记一次尝试结果。**同一个 `(坐标, 按键)` 以最新为准**——`attempts.pop` 后重新插入使其排到末尾（淘汰按"最近用过"走），超出 `MAX_TRIED` 删最早的键。理由：结果真的会变化（本来锁着的门后来开了、本来有人挡的路后来通了），旧结论留着比没有更糟——会让 agent 反复绕开已经通了的路。
- `see(line) -> None`：记一句台词，先尝试用 `_stitch` 和 `lines[-1]` 拼接，拼不上再判重复追加，然后调用 `_trim()`。**理由**：GB 对话框一次显示两行，按 `a` 滚一行，视觉模型每帧抄下可见部分，连续几帧抄回的是同一句话的多个重叠窗口；早一版只做完全相同去重，导致重叠窗口各占一格塞满 `MAX_OBJECT_LINES`，把带身份信息的第一句挤掉，实测档案里 NPC 最后只剩半截话、"这是谁"完全丢失。拼接是纯字符串运算（重叠部分接上），不需要模型也不引入新错误。
- `_trim() -> None`：超出 `MAX_OBJECT_LINES` 时保留第一条 + 最近的若干条。**理由**：第一条最不可替代（NPC 自我介绍、招牌标题常在开头），后续台词随剧情推进丢一句无所谓，丢了第一句这条档案就答不了"这是谁"。
- `render() -> str`：渲染成 `known_objects` 里一行。**"还没互动过"也要显式写出**——这是档案最有价值的一类条目（"这里有扇门，见过 7 次，一次都没进去过"是它自己的待办清单），没有这条信息就分不出哪扇门探索过、哪扇是新的。门类对象单独用 `leads_to` 判断（开没开是唯一要紧的问题，开了直接写结论；没开则原样列出 `attempts`，因为键本来就是"坐标→按键"，模型自己拿角色当时位置一比即知是推门还是站上按，不需要再翻译成"站在南边"这种措辞）。

### 5.5 常量：`MIN_STITCH = 6`（本文件内独立定义）

**设计理由**：取值理由同 `memory_episodic.py` 的同名常量，但两处**各自独立定义**，因为拼接的是两种不同的滚动窗口内容（对话滚动 vs. 情景记忆的文本片段），没有必要共用同一个值。

### 5.6 函数：`_stitch(prev, new) -> str | None`（本文件内独立定义）

逻辑与 `memory_episodic.py` 中的同名函数完全一致，供 `ObjectFact.see` 使用；同样是本文件独立复制而非跨文件共享的实现。

---

## 6. `trace.py`

依赖：`from .action import Action`（间接依赖 `observation.py`）。

模块定位：记账、判定结果、事件流；`ModelCall`/`Decision`/`Verdict` 出现在 `BrainPort` 签名里，`TraceEvent` 出现在 `TracePort` 签名里，均跨层。

### 6.1 `ModelCall`

一次模型调用留下的账，外加它成没成。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `payload` | `dict[str, str]` | `{}` | token、延迟、prompt 版本、第几次尝试、原始输出；**失败的调用也要有**——同样烧了钱，且保留 `raw` 可在改进解析器后离线重算，不必重跑烧 token |
| `error_kind` | `str` | `""` | 失败类型（`ParseFailure`/`IllegalAction`/`OutputTruncated`…）；空串表示成功。**单独一列**，聚合失败模式时不必解析 error 字符串 |
| `error` | `str` | `""` | 失败详情，一句话 |

**设计理由（为什么大脑要把账交出来、而不是自己记）**：**只有 Harness 写 trace**。大脑是被调用方，返回结果和账单，由 Harness 翻译成事件。上一版不是这样：brain 自己写 `MODEL_CALL`/`THINK`/`ERROR`/`MEMORY_READ` 事件，harness 写 `ACT`/`MEMORY_WRITE`/`OBSERVE`/`EPISODE_*`，导致"某类事件归谁写"要逐条记忆，还开了个例外——判定器不写 trace，为了让判定器碰不到自己的账。统一之后规则只有一句："谁控制循环，谁记账"；判定器碰不到自己的账因此不再是特权设计，而是所有大脑调用的共同处境。`payload` 直接就是 trace 里 `MODEL_CALL` 事件的内容；`error_kind` 非空时 Harness 会**另外补一条 `ERROR` 事件**——账单答"花了多少钱"，失败模式答"为什么没拿到东西"，混在一条里两者都统计不出来。

### 6.2 `Decision`

大脑选一次动作的全部产物：动作、账单、翻过哪些记忆。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `action` | `Action \| None` | `None` | 选中的动作；None 表示重试全部用尽——**这不是异常，是一类要被统计的失败模式** |
| `calls` | `list[ModelCall]` | `[]` | 每次尝试一条，成功失败都在里面，按发生顺序 |
| `recalled` | `list[str]` | `[]` | 取回了哪几条情景记忆，形如 `(episode_id, step)` |

**设计理由**：`action=None` 表示重试用尽，由 Harness（知道这一局死活的那一方）决定是否抛异常，大脑本身只如实汇报。`recalled` 记的是**引用而不是数量**——只记数量的话 replay 时无法回答"这个决策是被哪条经验影响的"，而这正是要检验"记忆到底有没有用"时必须查的东西。

### 6.3 `Verdict`

一次成败判定的结果，连同它花了什么。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `done` | `bool` | 必填 | 任务达成了没有，**拿不准一律 False** |
| `why` | `str` | 必填 | 看到了什么证据（或为什么证据不足）；每个 True 都得说得出依据，否则成功率是个无法证伪的数字 |
| `call` | `ModelCall` | `ModelCall()` | 这次判定自身的账 |

**设计理由**：这个类型跨层了才做成模型——大脑产出它，Harness 读 `done` 决定是否终止，把 `call` 写进 trace，两边对这三个字段的期待必须是同一份契约。判定自身的调用也要单独记账：判定和决策各自烧 token，分不开就说不清"成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率——而"没有失效率的判定器等于没有判定器"。

### 6.4 `EpisodeOutcome`

一次任务尝试的最终结果，是评测与机制三的输入。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `episode_id` | `str` | 必填 | 本次尝试标识 |
| `task_id` | `str` | 必填 | 尝试的是哪个任务 |
| `success` | `bool` | 必填 | 是否成功 |
| `steps` | `int` | 必填 | 实际用了多少步 |
| `reason` | `str` | 必填 | 终止原因：`success`/`failed`/`max_steps_exceeded`/`error` |

**用途**：成功率按 `task_id` 分组统计；MC（蒙特卡洛）回填拿 `success` 作为 episode 的最终回报沿轨迹往回传（机制三）。

### 6.5 常量：`TRACE_SCHEMA_VERSION = 2`

事件形状的版本号。

**设计理由**：事件形状还会变（当前已是第二版），老 JSONL 被新解析器读时不会报错，只会**静默读错**——少一个字段就当它是空的，多一个就忽略。版本号让"这批数据是旧格式"变成一句可判断的话，而不是隐性错误。

### 6.6 `Source`（`str, Enum`）

事件由哪一层产生：`PERCEPTION`（视觉模型链）、`DECISION`（文本模型链）、`HARNESS`（掩码/记忆/生命周期）、`WORLD`（模拟器）、`JUDGE`（成败判定，与决策分开记账才能算出判定器自己的准确率）。

**设计理由**：每种聚合几乎都要按它切分（感知/决策各烧多少 token，失败集中在哪一层，延迟花在哪），它是横切维度，因此放进事件"信封"字段而不是 `payload` 内容。

### 6.7 `EventType`（`str, Enum`）

trace 事件类型，取值：`EPISODE_START`、`EPISODE_END`、`OBSERVE`、`MODEL_CALL`、`THINK`、`ACT`、`MEMORY_READ`、`MEMORY_WRITE`、`OBJECT_NOTE`、`INSPECT`、`GOAL_PUSH`、`GOAL_POP`、`ERROR`、`CHECKPOINT`。

**分类设计理由**：
- `OBJECT_NOTE`（记下语义记忆·object 的新事实）与 `MEMORY_WRITE`（情景记忆写入）**故意分开**——二者是两种记忆（一次经过 vs. 那一格本身），寿命和用途不同；混成一类就数不出"它认识了多少个东西"这一直接反映语义记忆有没有用的指标。
- `INSPECT`（细看）与 `OBSERVE`（每步必发的常规观测）分开：`INSPECT` 是大脑主动要的，混在一起就算不出"它多久要细看一次"，无法判断这个动作值不值那次调用成本。
- `GOAL_PUSH`/`GOAL_POP` 拆成两类而不是一个带方向的字段：目标栈"拆了几层"和"完成了几层"是两个独立的数，拆得多完成得少正是目标栈失控的表现，按类型分开计数就能一眼看出。

### 6.8 `TraceEvent`

追加写的 trace 事件；是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因的共同底座。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `event_id` | `int` | 必填 | 全局单调递增；SSE 断线重连靠它补发，**排序的唯一依据** |
| `run_id` | `str` | 必填 | 哪一次实验；**manifest 的 join key**——没有它，记着模型与 prompt 的 manifest 无法与一堆事件对上 |
| `episode_id` | `str` | 必填 | 所属 episode |
| `step` | `int` | 必填 | 发生在第几步；**不是主键**，一步内可能有多条事件 |
| `type` | `EventType` | 必填 | 事件类型 |
| `source` | `Source` | 必填 | 由哪一层产生；成本拆分与失败归因都按它切 |
| `payload` | `dict[str, str]` | `{}` | 该类型的结构化内容 |
| `ts` | `float` | 必填 | Unix 时间戳（秒），用于算延迟、对齐外部日志；**不能替代 `event_id` 排序**——同毫秒多条事件、时钟回拨都会让时间序失真 |
| `schema_version` | `int` | `TRACE_SCHEMA_VERSION` | 事件形状版本号 |

**设计理由**：本类是**不可变的事件**，不是可变的状态快照——文档明确警告不要往里加"当前状态"这类字段，否则会破坏可重放性（replay 依赖事件流的纯追加、不可变特性）。
