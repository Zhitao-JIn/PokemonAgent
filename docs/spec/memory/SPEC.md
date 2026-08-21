# `pokemon_agent/memory/` 技术规格

覆盖文件：`memory/port.py`、`memory/util.py`、`memory/semantic/object_store.py`、
`memory/semantic/__init__.py`，以及它们所依赖的类型定义
`schemas/memory_semantic.py`（`ObjectFact`）、`schemas/observation.py`（`Place`、`Landmark`）。

---

## 1. 模块定位：语义记忆的纯存储层

`memory/` 包是"语义记忆（object semantic memory）"的**存储层**，它的边界由
`port.py` 顶部的 docstring 直接写明：

> "这是底层协议，不是大脑看到的接口。大脑连'语义记忆'这个词都不该知道；
> `tools/memory_tool.py` 里的 `MemoryTool` 组合这个协议、翻译成 Harness 能用的方法，
> `interfaces/tools.py` 的 `MemoryToolPort` 才是 Harness 真正认识的那一层。"

`object_store.py` 的类文档把边界说得更具体，并交代了这条边界的历史成因：

> "纯存储，没有编排逻辑。它只知道'按坐标存一条 `ObjectFact`、按坐标/按地图取'，
> 不知道'一次按键该查哪几格候选''这次尝试算不算数'这类**编排**问题——
> 那些是 `tools/memory_tool.py` 的活（它是 Harness 真正调用的那一层，
> 拿着 `before`/`action`/`after` 三个观测去决定该调这个类的哪个方法）。
>
> 这条边界是这次重写要立的规矩：以前的 `ObjectMemory.note_step()` 一个方法里
> 混了'这次按键碰到了什么候选''朝向算不算数''要不要跳过连按'和'写进哪条档案'——
> 存储和编排揉在一起，换存储后端（哪怕只是想加个 sqlite）就得把编排逻辑照抄一遍。
> 拆开之后这个类只有五个方法，**没有一个知道'按键''朝向''连按'这些游戏概念**。"

### 边界具体体现在哪些方法签名 / docstring 里

- `SemanticObjectWriter.see(marks: list[Landmark], stamp: str) -> None` 的前置条件写着
  "调用方保证一步只调一次"——这一层完全不知道"一步"是什么，它只负责按传进来的
  `Landmark` 列表建档，"什么算一步"是调用方（`MemoryTool`）要守的约束。
- `SemanticObjectWriter.touch(place, kind, text="")` 的 docstring："`kind` 由调用方给
  （当帧地标或档案兜底，见 `memory/util.py`），这一层不判断'这一格上到底是什么'——
  那是几何/解析的事，不是存储的事。"
- `SemanticObjectWriter.record_attempt(place, kind, key_desc, result)` 的前置条件："
  `result` 必须是 `RESULT_NONE` / `RESULT_DIALOG` / 或以 `RESULT_WARP_PREFIX` 开头——
  **这一层不校验**，校验值域是调用方的事（它就是算出这个值的人），这一层只管存。"

这三处共同说明：`key_desc`（按键+朝向的编码）、"这次算不算一次尝试"、`kind`/`result`
这些值**从哪里算出来**，全部发生在协议边界之外；`memory/` 只负责"给我一个已经算好的
值，我原样存进去、按坐标查回来"。

### 边界另一侧住在哪里

调用方是 `tools/memory_tool.py` 里的 `MemoryTool`——它拿着 `before`/`action`/`after`
三个观测决定该调 `ObjectMemory`（经由 `SemanticObjectStore` 协议）的哪个方法，
并把结果翻译成 `interfaces/tools.py` 的 `MemoryToolPort` 给 Harness/大脑用。
该文件本身是另一个模块的 spec 范围，这里只指出它的位置和职责分界，不展开。

---

## 2. `memory/port.py`：三个 Protocol

模块 docstring 把整体设计动机概括为一句话：

> "现在只有一类语义记忆：object（门/招牌/人）。协议按'输入 / 输出'拆成两半，
> 再合成一个'存储'协议，理由是三件事分别回答不同的问题：
>
> ```
> Reader   语义记忆能被查到什么           —— 输出
> Writer   什么样的观察会写进语义记忆      —— 输入
> Store    一个具体后端要满足的全集         —— 存储
> ```
>
> 拆成读写两半而不是一个 protocol，是为了将来某个消费方可能**只该读、不该写**——
> 比如给判定器一份只读视图，类型层面就能保证它写不进去，不用靠约定。"

三个 Protocol 都用 `@runtime_checkable` 装饰，`from __future__ import annotations`。
依赖的类型：`ObjectFact`（来自 `schemas/memory_semantic.py`）、`Landmark`/`Place`
（来自 `schemas/observation.py`）。

### 2.1 `SemanticObjectReader`

"语义记忆（object）的读端：查'世界是什么样'，不改变任何状态。"

#### `query(self, place: Place) -> ObjectFact | None`

- **签名**：给一个 `Place`（`map_id, x, y`），返回该格档案或 `None`。
- **后置条件（docstring 明确规定的行为契约）**："这一格有没有档案。**没有就返回
  None，不返回空对象**——调用方要能区分'这一格什么都不知道'和'知道但是空的'，
  后者在这套设计里不会出现（`touch()`/`record_attempt()`/`see()` 建档时至少会留下
  `seen`/`touched` 计数），但协议不该靠'反正不会发生'去回避这个区分。"
  也就是说：协议层面仍然承诺返回值可以是 `None`，即使当前唯一实现下"空对象"
  这种情况实际不会出现。

#### `query_map(self, map_id: int) -> list[ObjectFact]`

- **签名**：给一个地图编号，返回这张地图上全部档案。
- **契约**："这张地图上全部档案，**未排序**——排序、筛选、渲染成文字都是调用方
  的事。只按地图筛，不按屏幕筛：见 `ObjectMemory`（具体实现）的说明，协议这一层
  只需要知道'按地图筛'这个粒度就够了。"即协议只保证按 `map_id` 过滤这一个粒度，
  不保证顺序，也不提供按屏幕范围筛选的能力。

### 2.2 `SemanticObjectWriter`

"语义记忆（object）的写端：三种写入对应三类不同的观察，**不合并成一个方法**——
合并了就没法在类型层面看出'这次调用到底在断言什么'，而这三类断言的可信来源
完全不同（说明见各自的 docstring）。"

#### `see(self, marks: list[Landmark], stamp: str) -> None`

- "这一帧看到的地标全部记一遍 `seen`，**没互动过的也建档**。"
- **前置条件**："`stamp` 非空，且**调用方保证一步只调一次**——`seen` 答的是
  '进过几次视野'，调两次这个数就没有意义了，但这一层不知道'一步'是什么，
  这条约束靠调用方（`MemoryTool`）守。"
- 无返回值。

#### `touch(self, place: Place, kind: str, text: str = "") -> ObjectFact`

- "确认这一格上有个东西：建档或取已有档案，`touched += 1`；`text` 非空则记一句。"
- "`kind` 由调用方给（当帧地标或档案兜底，见 `memory/util.py`），这一层不判断
  '这一格上到底是什么'——那是几何/解析的事，不是存储的事。"
- 返回更新后的 `ObjectFact`。

#### `record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact`

- "记下一次尝试：`place` 上那个东西，在 `key_desc` 这个姿势下，结果是 `result`。"
- **前置条件**："`key_desc`、`result` 非空。`result` 必须是 `RESULT_NONE` /
  `RESULT_DIALOG` / 或以 `RESULT_WARP_PREFIX` 开头——**这一层不校验**，校验值域是
  调用方的事（它就是算出这个值的人），这一层只管存。"
- 返回更新后的 `ObjectFact`。

### 2.3 `SemanticObjectStore`

```python
class SemanticObjectStore(SemanticObjectReader, SemanticObjectWriter, Protocol):
    """存储协议：读写的并集，是一个具体后端（ObjectMemory）要满足的全集。"""
```

- 不新增任何方法，纯粹是 `Reader` 和 `Writer` 的合并，是"一个具体后端要满足的
  全集"这句设计要求的直接落地：想要一个只读视图，声明依赖 `SemanticObjectReader`；
  想要一个完整可换后端的实现，声明依赖/实现 `SemanticObjectStore`。
- `port.py` 顶部说明了这个协议存在的实际用途：换存储后端（比如换成 sqlite）
  只需要另写一个类满足这个协议，`MemoryTool` 和它的调用方一行都不用改。

---

## 3. `memory/util.py`：三个纯函数

模块 docstring："纯函数：算坐标、解析当帧地标。**不碰任何存储状态**——这是它们和
`memory/semantic/object_store.py`（有状态的 `_objects` 字典）的唯一区别，也是拆成
单独文件的理由：纯函数可以脱离'有没有建过档'单独测试和复用，将来别的语义记忆类别
要用同样的'查一圈'逻辑时，不需要牵连任何存储实现。"

依赖：`schemas/observation.py` 的 `FACING_STEP`、`Landmark`、`Observation`、`Place`。

### 3.1 `surrounding_cells(place: Place) -> list[Place]`

```python
def surrounding_cells(place: Place) -> list[Place]:
    return [place] + [
        Place(map_id=place.map_id, x=place.x + dx, y=place.y + dy)
        for dx, dy in FACING_STEP.values()
    ]
```

- **算法**：`place` 本身 + 沿 `FACING_STEP` 四个朝向各偏移一格，共 5 格（一个
  "十"字形，含中心）。
- **为什么是这 5 格**："这是一次方向键按下去唯一可能影响到的范围——按键要么改变
  自己脚下这格的状态（踩在门上朝外按），要么作用在某个相邻格上（从旁边推）。
  `FACING_STEP` 只有四个朝向，穷尽，不需要再单独判断'往哪边扩展'。"
- **命名理由（为什么不叫 `ring`）**："这五格是'十'字形（含中心），不是环——
  严格意义上的'一圈'应该排除中心，而中心（脚下）恰恰是最容易被漏掉、也最要紧的
  一格（人物精灵盖住它，当帧 `landmarks` 报不出来）。名字里不该带一个会让人以为
  '脚下不算'的词。"
- **调用者**：文中未在这四个文件内直接看到调用点；按注释语境，这是给
  `tools/memory_tool.py` 编排"一次按键该查哪几格候选"时使用的候选格生成函数
  （即"按键要么改变脚下这格状态，要么作用在相邻格"这句话对应的正是编排层要枚举
  的候选集合）。

### 3.2 `parse_landmarks(obs: Observation) -> list[Landmark]`

```python
def parse_landmarks(obs: Observation) -> list[Landmark]:
    if obs.place is None:
        return []
    out: list[Landmark] = []
    for item in obs.facts.get("landmarks", "").split("; "):
        parts = item.split()
        if len(parts) != 3 or not parts[1].startswith("x=") or not parts[2].startswith("y="):
            continue
        out.append(Landmark(
            kind=parts[0],
            place=Place(map_id=obs.place.map_id,
                        x=int(parts[1][2:]), y=int(parts[2][2:])),
        ))
    return out
```

- **算法**：`obs.place` 为空直接返回空列表；否则读 `obs.facts["landmarks"]`
  这个字符串（形如 `门 x=13 y=5; 人 x=2 y=7`），按 `"; "` 切分成条目，每条再按空格
  切成 3 段，校验第 2、3 段分别以 `x=`/`y=` 开头，不满足格式的条目直接跳过；
  合法的条目组装成 `Landmark(kind=..., place=Place(map_id=obs.place.map_id, x=.., y=..))`。
  地图编号取自 `obs.place.map_id`，不从字符串里解析。
- **为什么要解析字符串而不是直接拿结构化数据**："只在这里解析一次，而且解析的是
  我们自己刚渲染出去的格式（`门 x=13 y=5; 人 x=2 y=7`）。真正干净的做法是让
  `Observation` 直接带结构化的 landmarks，但那要给跨层契约再加一个字段，而目前
  只有语义记忆这一个消费方——等第二个消费方出现再提上去。"（这段同时解释了为什么
  `Observation.facts["landmarks"]` 这条字符串格式与
  `schemas/observation.py` 里 `Landmark.render()` / `TerrainMap.render_landmarks()`
  产出的格式必须一致——渲染方和解析方目前都在这条数据管道的两端，各自独立实现，
  由约定的格式串联。）
- **调用者**：本文件内的 `kind_in_frame` 直接调用它；从设计动机看，`MemoryTool`
  在决定"这次尝试碰到的是什么"时，也需要走这条解析路径拿到当帧地标。

### 3.3 `kind_in_frame(obs: Observation, place: Place, interactive: tuple[str, ...]) -> str | None`

```python
def kind_in_frame(obs: Observation, place: Place, interactive: tuple[str, ...]) -> str | None:
    for mark in parse_landmarks(obs):
        if mark.place.key == place.key and mark.kind in interactive:
            return mark.kind
    return None
```

- **算法**：调用 `parse_landmarks(obs)` 得到当帧地标列表，找 `place.key` 匹配、
  且 `kind` 落在 `interactive`（调用方传入的"算互动"的类型白名单，例如门/招牌/人）
  内的第一条，返回其 `kind`；找不到返回 `None`。
- **为什么单独拆出来（相对于 `object_store.py` 里的档案兜底逻辑）**："**只看
  当帧**：`place` 这一格在这一帧的 `landmarks` 里是什么。认不出来返回 `None`。
  这是 `kind_at`（在 `object_store.py` 里，档案兜底那一半）拆出来的**当帧那一半**
  ——拆开是因为这一半是无状态的纯查询，档案那一半要碰 `_objects`，两者的可信
  来源也不同：这一半答的是'这一帧确实看见了'，另一半答的是'我以前见过那里有
  什么'（当帧看不见时补上，比如人物精灵盖住了脚下的门）。"
  说明：docstring 中提到的 `kind_at` 方法在本次读取的
  `memory/semantic/object_store.py` 源码中**没有出现**（该文件当前只有五个方法：
  `query`/`query_map`/`see`/`touch`/`record_attempt`）；docstring 引用的这个
  "档案兜底那一半"逻辑推测由调用方（`MemoryTool`）自行组合
  `kind_in_frame` 与 `ObjectMemory.query()` 的结果实现，而不是 `object_store.py`
  内部的一个方法——文档与当前源码之间的这一处出入按代码事实原样记录，不做臆测填补。
- **调用者**：设计意图上是给 `MemoryTool` 判断"这一步按键对应的对象类型"用的
  当帧优先来源，档案（`ObjectFact.landmark.kind`）是它看不见时的兜底。

---

## 4. `memory/semantic/object_store.py`：`ObjectMemory`

### 4.1 实现的协议

`ObjectMemory` 实现 `SemanticObjectStore`（即同时满足 `SemanticObjectReader` 与
`SemanticObjectWriter`）。类文档强调它是"`SemanticObjectStore` 协议（见
`memory/port.py`）的具体实现"，且"不随 episode 清空"：

> "'地图39 x=2 y=3 那个人不是母亲'这件事，下一局仍然成立，跨局复用正是要验证
> 的东西。清空的话机是每次 `Harness.reset()` 该做的事，不是这个类自己的责任。"

### 4.2 内部数据结构

```python
def __init__(self) -> None:
    self._objects: dict[str, ObjectFact] = {}
```

- 唯一的状态：`self._objects`，一个 `dict[str, ObjectFact]`。
- **key**：`Place.key`（`schemas/observation.py` 中定义为
  `f"{self.map_id}:{self.x}:{self.y}"`），即"`(map_id,x,y)` 的 key"——跨 episode
  稳定的字符串键。
- **value**：一条 `ObjectFact`（定义于 `schemas/memory_semantic.py`，见第 5 节）。
- 类注释直接点明："**语义记忆的全部状态都在这一个字典里。**"

### 4.3 各方法行为

#### Reader 部分

- `query(self, place: Place) -> ObjectFact | None`
  ```python
  return self._objects.get(place.key)
  ```
  按 `place.key` 直接查字典，没有就是 `None`，与协议契约一致。

- `query_map(self, map_id: int) -> list[ObjectFact]`
  ```python
  return [f for f in self._objects.values() if f.landmark.place.map_id == map_id]
  ```
  遍历全部档案，按 `f.landmark.place.map_id` 过滤；不做任何排序，与协议中
  "未排序"的承诺一致。

#### Writer 部分

- `see(self, marks: list[Landmark], stamp: str) -> None`
  ```python
  for mark in marks:
      fact = self._objects.setdefault(
          mark.place.key, ObjectFact(landmark=mark, first_seen=stamp)
      )
      fact.seen += 1
      fact.last_seen = stamp
  ```
  对传入的每个 `Landmark`：若该格已有档案则取出，否则以该 `Landmark` 和
  `first_seen=stamp` 新建一条档案并放入字典（`setdefault` 保证不覆盖已有档案的
  `first_seen`）；无论新建还是取旧，都把 `seen` 计数加一、`last_seen` 更新为
  当前 `stamp`。这正是协议 docstring 所说"没互动过的也建档"。

- `touch(self, place: Place, kind: str, text: str = "") -> ObjectFact`
  ```python
  fact = self._objects.setdefault(
      place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
  )
  fact.touched += 1
  if text:
      fact.see(text)
  return fact
  ```
  按 `place.key` 取已有档案，或以调用方给的 `kind` 新建一条（此路径下
  `first_seen` 使用 `ObjectFact` 的默认值，不像 `see()` 那样传入 `stamp`）；
  `touched` 计数加一；若 `text` 非空，调用 `ObjectFact.see(text)`
  （定义在 `schemas/memory_semantic.py`，做滚动窗口文本拼接，见第 5 节）
  把这句话记入 `lines`。返回该档案。

- `record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact`
  ```python
  fact = self._objects.setdefault(
      place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
  )
  fact.record(key_desc, result)
  return fact
  ```
  同样按 `place.key` 取或建档案，然后调用 `ObjectFact.record(key_desc, result)`
  （见第 5 节：以 `key_desc` 为键覆盖式写入 `attempts`，超出 `MAX_TRIED` 时淘汰
  最早一条）。注意：`ObjectMemory.record_attempt` 本身不对 `key_desc`/`result`
  做非空校验——这一校验被 `ObjectFact.record()` 内部做了（`if not key_desc or not
  result: return`），与协议 docstring "这一层不校验"（指 `ObjectMemory`/协议层
  不校验值域，而不是完全不做空值防御）的说法一致：值域校验（是否属于
  `RESULT_NONE`/`RESULT_DIALOG`/`RESULT_WARP_PREFIX` 三者之一）确实不在
  `ObjectMemory` 或 `ObjectFact.record()` 里做，由调用方负责算出合法值。

### 4.4 五个方法与"游戏概念无关"

`ObjectMemory` 的五个公开方法（`query`、`query_map`、`see`、`touch`、
`record_attempt`）签名中只出现坐标（`Place`）、类型字符串（`kind`）、
自由文本（`text`/`key_desc`/`result`/`stamp`），不出现任何按键名、方向、
"连续按键是否算一次"这类概念——这正是第 1 节所述边界的落地证据。

---

## 5. `memory/` 与 `schemas/` 层的关系：为什么 `ObjectFact` 不在这个包内部

`memory/port.py` 与 `memory/semantic/object_store.py` 读写的数据类型
`ObjectFact`，其定义位于 `schemas/memory_semantic.py`，不在 `memory/` 包内部。
`schemas/memory_semantic.py` 顶部与 `ObjectFact` 类文档给出了理由：

1. **它是跨层契约的一部分，但只跨这一小段**：
   > "从不出现在 `WorldPort`/`GameToolPort` 的签名里，只出现在 `MemoryToolPort`
   > （见 `interfaces/tools.py`）——大脑不该知道'语义记忆''ObjectFact'这些词，
   > 它看到的只是 `known_objects` 里的一段渲染文字。"
   `ObjectFact` 需要被 `memory/port.py` 的协议签名、`memory/semantic/object_store.py`
   的实现、以及 `interfaces/tools.py` 的 `MemoryToolPort`（供 Harness/`MemoryTool`
   使用）三处共同引用，因此它是一个**跨模块共享的数据契约**，而不是
   `memory/` 包私有的实现细节——放进 `schemas/` 与 `Landmark`、`Place`
   （同样是跨层契约，定义在 `schemas/observation.py`）并列，是把"契约"和
   "实现契约的存储逻辑"分开摆放的自然结果。

2. **`ObjectFact` 自身携带的行为（`record`、`see`、`_trim`、`render`、
   `leads_to` 属性）是"这一类事实的存储形状"该有的行为，与"按坐标存取"这件
   存储层的事是两回事**：`ObjectFact.record()` 负责一个对象内部"姿势→结果"表
   的覆盖式写入与超限淘汰（`MAX_TRIED = 8`，"一扇门总共只有 8 种碰法……
   试过的不淘汰——超过上限时丢最早的一条"）；`ObjectFact.see()` 负责台词的
   滚动窗口拼接（GB 对话框一次显示两行、按 `a` 滚一行，同一句话被拆成多个
   重叠窗口抄回来，需要用 `_stitch()` 做字符串重叠拼接，且第一条永远保留
   因为"NPC 的自我介绍……都在开头"）；`ObjectFact.render()` 负责把一条档案
   渲染成 `known_objects` 里的一行文字，并对"门"做特殊处理（用
   `leads_to`——一个从 `attempts` 里动态算出、而非单独存储的字段——直接给出
   "通往地图N"这样的结论，避免"两处真相"不一致）。这些是**这一类事实自己的
   业务规则**，`memory/` 包（`ObjectMemory`/协议）完全不碰这些规则，只把
   整个 `ObjectFact` 对象当成一个不透明的值来存取——这正对应第 1 节所述
   "存储层不知道游戏规则"的边界，`ObjectFact` 的方法体现的正是那些被排除在
   `memory/` 包之外的规则应该放在哪里：数据自己的模型里，而不是存储实现里。

3. **命名沿革也支持这一分层**：`ObjectFact` 是从早期的 `ObjectNote`
   （"记了一笔"）改名而来，"搬进语义记忆这一层之后它的身份更明确了——它是
   语义记忆里'object'这一类事实的存储形状"，且为将来"语义记忆还会有更多用途
   （比如从 `attempts` 里学出'这一类地形的门都要从北边推'这种跨对象的规律）"
   留了名字上的扩展空间；这类演化属于"事实模型该长成什么样"的问题，
   与"怎么把一个事实模型存进 dict、按 key 取出来"（`memory/` 包的职责）
   是两个独立的关注点，因此分属两个包。

`Place`、`Landmark` 同样定义在 `schemas/observation.py` 而非 `memory/`，
理由与之平行：`Place` 是"全项目唯一的'位置'表示"，"因为它现在承载记忆的键：
语义记忆按 `(map_id, x, y)` 索引，那三个数必须整体传递、整体比较"，同时它也
出现在 `WorldPort`/`GameToolPort` 等更上层的跨层契约里，不是 `memory/`
包能独占的类型；`Landmark`（门/招牌/人的类型+位置，"没有名字"）由感知层
（`PyBoyWorld`/`TerrainMap.landmarks()`）产出，是 `memory/util.py`
的 `parse_landmarks`/`kind_in_frame` 与 `memory/semantic/object_store.py`
的 `see`/`touch`/`record_attempt` 共同消费的输入类型，同样是跨层契约的一部分。
