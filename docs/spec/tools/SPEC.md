# `pokemon_agent/tools/` 模块技术规格

本规格覆盖 `pokemon_agent/tools/game_tools.py`（`GameTools`）与
`pokemon_agent/tools/memory_tool.py`（`MemoryTool`），并结合它们各自实现的协议
（`interfaces/tools.py` 的 `GameToolPort`/`MemoryToolPort`）、`GameTools` 包装的
`interfaces/world.py`（`WorldPort`）、`MemoryTool` 包装的 `memory/port.py`
（`SemanticObjectStore`）说明其契约与设计动机。所有结论均来自源码与源码内的
中文 docstring，不做额外引申。

---

## 1. 模块定位：Harness 伸向环境和记忆的两只手

`tools/` 目录下只有两个类，各自实现一个协议：

| 类 | 实现的协议 | 只碰什么 |
|---|---|---|
| `GameTools` | `GameToolPort` | 只碰 `WorldPort`（环境），**不碰任何记忆** |
| `MemoryTool` | `MemoryToolPort` | 只碰 `memory/` 包（记忆），**不碰世界** |

`interfaces/tools.py` 的模块 docstring 把这个拆分讲得很直接：以前只有一个
`ToolHost`（另外还有一个更小的 `ToolPort` 给大脑用），"感知世界"和"记忆"混在
同一个协议、同一个实现类（`GameTools`）里。现在大脑不再持有任何工具实例——
`Brain.choose()` 需要的情景记忆由 Harness 先查好、当参数传进去，大脑不再有机会
主动调用 `GameToolPort`/`MemoryToolPort` 的任何方法，所以给大脑看的 `ToolPort`
协议也就没有存在必要了。

拆成 `GameToolPort`/`MemoryToolPort` 两个协议而不是一个，是因为它们的实现本来
就该是两个不相关的类（`GameTools` 只碰 `WorldPort`，`MemoryTool` 只碰 `memory/`
包），揉进一个协议会让人误以为它们必须由同一个对象同时实现。`Harness.__init__`
因此收两个参数：`game: GameToolPort` 和 `memory: MemoryToolPort`。

`game_tools.py` 的模块 docstring 补充了这次拆分之前的坑：`GameTools` 以前还叫
`Harness`，那个名字盖住了两件不同的事——"怎么碰环境"（这里）和"一局怎么跑"
（`harness/harness.py`）。合在一个类里的时候，`perceive()` 同时是"看一眼"和
"新的一步"，于是需要按步去重来调和两种身份，而那个去重制造了**步号回退**和
**判定重复计费**这两类实测出现过的 bug。拆开之后 `GameTools` **没有任何跨步骤
状态**，只有"上一次给出的动作空间"（`_last_space`）；它不写 trace、不认识
LLM、不知道 episode 是谁。

同样地，早先 `GameTools` 还持有一份 `ObjectMemory` 的引用，`perceive()` 顺手把
语义记忆拼进 `facts["known_objects"]`；这条耦合已被拆掉。`GameTools` 现在没有
任何字段指向记忆，`memory/` 包整个是它看不见的东西。`known_objects`/`knowledge`
现在由 `Harness._retrieve_memory()`（**不是** `_observe()`——两者都是语义记忆的
读，属于图上专门的"查记忆"节点，不属于"看一眼"）在拿到 `GameTools.perceive()`
结果、判定跑完之后，**另外**调 `MemoryToolPort.known_here()`/`knowledge_base()`
拼上去——两个协议各管各的，组合是 Harness 的活。

---

## 2. `GameTools`：`GameToolPort` 的唯一实现

### 2.1 构造函数与字段

```python
class GameTools:
    def __init__(self, world: WorldPort) -> None:
        self._world = world
        self._last_space: tuple[ActionSpace, str] | None = None
```

- `_world: WorldPort` —— 唯一的依赖，持有世界。构造后不再改变。
- `_last_space: tuple[ActionSpace, str] | None` —— "上一次交出去的动作空间，
  **连同它是给哪一帧算的**"。它回答两个问题，缺一不可：

  1. `execute()` 里那个动作确实来自最近一次 `get_action_space()`（不是大脑
     幻觉出来的名字）；
  2. 那次动作空间**没有过期**——画面换过之后再拿旧清单放行，就是在一个已经
     变了的世界里按一个按当时语境选的键。

  所以把帧哈希（`ActionSpace` + `last_frame_sha` 组成的二元组）一起存下来，
  让"这份清单过期了"变成一条能当场炸掉的契约（见 2.5 节 `execute()` 的
  assert）。

### 2.2 `reset(task: Task) -> PerceptionResult`

开新一局：先清空 `_last_space = None`（旧的动作空间对新局无意义），再转发给
`self._world.reset(task)`。

### 2.3 `perceive() -> PerceptionResult`

看一眼当前画面，直接转发 `self._world.observe()`。world 自己按帧缓存，所以
一帧之内调多少次都只花一次感知的钱。`result.calls` 直接是 `world.observe()`
交出来的那份，原样转发——这一层不做任何记账相关的事。

### 2.4 `inspect(focus: str) -> PerceptionResult`

对同一帧再问一次感知，转发给 `world.inspect(focus)`。前置条件用 assert 守：
`assert focus.strip(), "inspect() got an empty focus"`。换的是 prompt，不是
画面。

### 2.5 `get_action_space() -> ActionSpace`

**掩码发生在这里，只看 overlay。** 完整逻辑：

```python
obs = self._world.observe().observation
overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

assert names, f"action space must never be empty (overlay={overlay})"
space = ActionSpace(
    names=names,
    descriptions=dict(BUTTON_HELP[overlay]),
    note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
)
self._last_space = (space, self._world.last_frame_sha)
return space
```

**掩码规则的具体算法**：从 `obs.facts["overlay"]`（缺省 `Overlay.NONE.value`）
读出当前的 `Overlay` 枚举值，用它去查常量表 `OVERLAY_ACTIONS[overlay]` 得到
"这个 overlay 下理论上可用的动作名列表"，再和 `self._world.all_actions()`
（世界支持的全部动作名）取交集——即 `names = [a for a in OVERLAY_ACTIONS[overlay]
if a in self._world.all_actions()]`。`descriptions` 同样按 overlay 从
`BUTTON_HELP[overlay]` 取。

为什么掩码挂在 overlay 上而不是别的信号，docstring 给出了明确理由：**掩码是
策略，所以在这一层；`overlay` 是感知的产物，所以由 world 交出来**。两边通过
`Observation.facts` 这个公开字段衔接，谁也不认识谁的内部。而且 `overlay` 在
熔断测试里 **23/23 全对**，是整条感知链里最可靠的一维——把动作空间挂在它上面
是刻意的：分类错一次的代价是大脑看到一组不该有的动作，比字段读错严重得多。

后置条件用 assert 硬守：`names` 绝不能为空——走投无路也必须给至少一个动作，
空动作空间是这一层的 bug，不能推给大脑处理。

`intents` 字段留空（`ActionSpace` 默认只有 press），由 Harness 覆写：能不能
拆子目标取决于目标栈有多深，工具层不知道也不该知道。

方法末尾把 `(space, self._world.last_frame_sha)` 存入 `_last_space`——注释强调
"掩码是**按这一帧的 overlay 算的**，换帧就作废"。

关于该方法内部丢弃 `observe()` 返回的 `calls`：代码注释解释这是安全的，因为
调用方（`Harness._space`）总是紧跟在 `_observe()` 之后同一步内调用这个方法，
画面没变过，这次 `observe()` 必然命中缓存、`calls` 必然是空列表——真正的账
已经在 `_observe()` 里记过了。

### 2.6 `execute(action: Action) -> ToolResult`

```python
def execute(self, action: Action) -> ToolResult:
    assert self._last_space is not None, "execute() before get_action_space()"
    space, frame = self._last_space
    assert space.contains(action.name), (
        f"execute() got {action.name!r} outside {space.names}"
    )
    assert frame == self._world.last_frame_sha, (
        "execute() got an action space computed for an older frame "
        f"({frame} != {self._world.last_frame_sha}) — call get_action_space() again"
    )

    result = self._world.step(action)
    self._last_space = None

    assert result.observation is not None, "world.step() must return the new observation"
    return result
```

三个 assert 各防一类坑：

1. `self._last_space is not None`：防止**没调过 `get_action_space()` 就直接
   `execute()`**——没有可对照的动作空间，任何动作都无从验证合法性。
2. `space.contains(action.name)`：防止**大脑幻觉出不存在的动作名**。
3. `frame == self._world.last_frame_sha`：防止**用过期的动作空间去执行动作**。
   docstring 特别指出，只查名字是不够的：`a` 在野外、对话框、选择框里都可用，
   **名字对得上不代表语境对得上**。画面换过之后再拿旧清单放行，就是在一个
   已经变了的世界里按一个按当时语境选的键。

`execute()` 推进世界后立刻把 `_last_space` 置回 `None`——世界推进了，上一次的
动作空间自然失效，强制调用方在下一步前重新调用 `get_action_space()`。最后
assert `result.observation is not None` 作为后置条件——`world.step()` 必须
返回新观测。

### 2.7 `last_frame_sha`（property）

```python
@property
def last_frame_sha(self) -> str:
    return self._world.last_frame_sha
```

直接转发 `world.last_frame_sha`，用于追查"一条读错的观测是哪一帧"。

### 2.8 感知归 world，这一层只是转发

模块 docstring 说明了这一分工的边界：用户定的分工是**感知是"tool 调用
world"**。`VisionProvider` 留在 `PyBoyWorld` 里，理由是 `Observation` 是跨层
契约，谁产出谁负责完整性；而且"一帧只感知一次"的缓存依赖它在 world 内部实现。
`GameTools` 这一层只把 `observe()` 转出来，不掺杂任何自己的逻辑。

---

## 3. `MemoryTool`：`MemoryToolPort` 的唯一实现

### 3.1 构造函数与字段

```python
class MemoryTool:
    def __init__(self, objects: SemanticObjectStore | None = None) -> None:
        self._episodes: list[MemoryEntry] = []
        self._objects: SemanticObjectStore = objects or ObjectMemory()
```

- `_episodes: list[MemoryEntry]` —— 情景记忆，简单的列表。
- `_objects: SemanticObjectStore` —— 语义记忆（object）存储，默认创建一个
  `ObjectMemory()`，但接受注入。docstring 强调：**类型标成协议**（
  `SemanticObjectStore`），测试可以喂一个假实现，将来换存储后端也不用碰这个
  类的任何一行。

模块 docstring 说明为什么两类记忆不合并成一套方法：情景记忆按相似度/时间
检索，语义记忆按坐标查，读写语义完全不同。并且明确职责边界：**这一层做
编排，`memory/semantic/object_store.py` 只做存储**。"一次按键该查哪几格候选"
"朝向算不算数""连按要不要跳过"这些游戏规则性质的判断都在 `MemoryTool`——
`ObjectMemory` 只知道怎么按坐标存取一条 `ObjectFact`，不知道"按键"是什么。

程序记忆（procedural）还未实现，docstring 特意说明**不为其预留空方法**：
协议和实现都不该为一个还不存在的东西预留形状，等真的要做的时候再看它需要
什么样的读写接口。

### 3.2 情景记忆（episodic）

#### 3.2.1 `query_episodic(query: str, limit: int = 5) -> list[MemoryEntry]`

```python
assert limit > 0, f"limit must be > 0, got {limit}"

scored = sorted(
    self._episodes,
    key=lambda m: (self._overlap(query, m.render()), m.step),
    reverse=True,
)
hits = [m for m in scored if self._overlap(query, m.render()) > 0][:limit]

assert len(hits) <= limit, "query_episodic must respect the limit"
return hits
```

排序键是 `(重叠分, m.step)` 二元组、降序——重叠分相同时按 `step` 倒序（更新
的排前）。只保留重叠分 > 0 的条目，再截到 `limit` 条。

打分对着 `render()` 的文本，并且 docstring 特别强调**这必须和喂进 prompt 的
是同一份**：分开算的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，
而且不报错。

`_overlap` 静态方法：

```python
@staticmethod
def _overlap(query: str, content: str) -> int:
    return len(set(query) & set(content))
```

即把 `query` 和 `content` 各自转成**字符集合**，取交集大小作为分数——纯粹的
字符重叠计数，不涉及分词、TF-IDF 或向量。

docstring 用一整段坦白这个算法在中文上的局限：中文条目里"的、了、是、在、
边"这类字随处都有，任意两条中文文本的重叠数几乎恒大于零。实测查"北边是
草丛"，一条讲"南边有水面"的记忆也会被选中——只因为共用了一个"边"字。排序
还是对的（相关那条重叠数明显更高），但**筛选形同虚设**，实际效果接近"按
step 倒序返回最近 N 条"。写这段的用意：做「有记忆 vs 无记忆」的 A/B 实验时，
很容易把"最近 N 条也有用"误读成"检索有用"——那是两个完全不同的结论。文中
预告"机制一（状态归并 + 向量检索）"要换掉的就是这个方法体。

#### 3.2.2 `recent(episode_id: str, limit: int) -> list[MemoryEntry]`

```python
assert limit > 0, "recent() needs a positive limit"
return [m for m in self._episodes if m.episode_id == episode_id][-limit:]
```

按时间顺序（列表天然的写入顺序）取**这一局**（`episode_id` 过滤）最近
`limit` 条。docstring 强调它和 `query_episodic` 是两件不能互相替代的事：

- `query_episodic` 按相似度找"以前遇到过的类似情形"，**跨 episode**，给的是
  经验。
- `recent` 按时间取"刚刚发生了什么"，**只限本局**，给的是证据。

只限本局是关键的一条线：判定器需要历史（证据可能出现在三步以前那一帧的
对话框里），但跨 episode 的历史会造出另一种错——上一局说过的那句话让它在
**第 0 步**就判完成。

#### 3.2.3 `write_episodic(entry: MemoryEntry) -> None`

```python
assert entry.rationale, "write_episodic() got an entry without a rationale"
self._episodes.append(entry)
```

前置条件：`entry.rationale` 非空——没有理由的经验取回来也没用，它说不出
当时为什么这么判断，也就无法检查那个判断现在还成不成立。

#### 3.2.4 `episodic_size`（property）

```python
@property
def episodic_size(self) -> int:
    return len(self._episodes)
```

docstring：库里有多少条情景记忆，**它是 A/B 实验的自变量本身**，要能被记进
`EPISODE_START`（事件流）。

### 3.3 语义记忆（object）

#### 3.3.1 `known_here(obs: Observation) -> str`

```python
if obs.place is None:
    return ""
lines = [fact.render() for fact in self._objects.query_map(obs.place.map_id)]
return "\n".join(sorted(lines))
```

拿这张地图（`obs.place.map_id`）上"我互动过的那些格子分别给了什么"拼成
`known_objects` 用的文字，按 `sorted()` 排序后用换行拼接。

**只筛当前地图，不筛当前屏幕**：地图内的条目一共也没几条，而"屏幕外那扇门
我进去过"恰恰是它规划路线时最需要的一条；筛屏幕反而把最有用的滤掉了。

坐标和 `landmarks` 是同一套（全局 `x= y=`），所以模型不需要做任何换算就能把
两边对上——**它做不好的正是换算**。

#### 3.3.2 `see_objects(obs: Observation, stamp: str) -> None`

```python
self._objects.see(parse_landmarks(obs), stamp)
```

把这一帧看到的地标全部记进语义记忆（`ObjectMemory.see()`），没互动过的也记。

前置条件：**一步只调一次**——`seen` 是"进过几次视野"，调两次这个数就没有
意义了。调用方是 `Harness._observe()`，那里本来就是全项目唯一一步产出一次
观测的地方。

为什么没互动过的也要建档：这份档案最有价值的一类条目正是"**这里有一扇门，
我见过 7 次，一次都没进去过**"。没有它，agent 只能从 `landmarks` 看到那里
有扇门，**分不出哪扇是探索过的、哪扇是新的**——而那正是它规划下一步要去哪的
依据。

#### 3.3.3 `INTERACTIVE` 常量

```python
INTERACTIVE = ("人", "招牌", "门")
```

模块级常量，注释：哪些地标值得记一条语义记忆。走得过去的空地按 `a` 什么也不
会发生，记了是噪声。它在 `_kind_at` 中用于过滤 `kind_in_frame(...)` 的候选
地标种类，也用于判断从语义记忆里查到的兜底条目 (`fact.landmark.kind`) 是否
属于"值得当作交互对象"的种类。

#### 3.3.4 `note_step(before, action, after) -> list[ObjectFact]` —— 详细拆解

这是本类中最复杂的方法。它回答"这一步碰到了什么，记进语义记忆"，返回被
更新的条目（可能为空）。docstring 先说明为什么把三件事合成一个方法：**互动**
（按 `a`）、**姿势**（按方向键：从旁边推过去 / 站在它上面朝外按）、**穿门**
（姿势的结果是换了地图）——它们共用同一个触发点（走完一步之后）。

**核心洞察——姿势是这一步唯一新增的一维**：用户的原话是"有的门走上前就行，
有的要踩在门上撞墙，有些坡只有一个方向能走"。这三件事的差别只有两维——
**我人在它旁边还是在它上面**、**按的哪个方向**——两维本身就是"角色当时的
坐标"和"按了哪个键"，不用再翻译成专门的姿势名字，所以存成
`attempts[x=.. y=..→按键] = 结果`。结果也是算的：`before.place` 和
`after.place` 一减，换图 / 无效果。

**面朝哪一格是算出来的，不是认的**：`place`（内存读的全局坐标）+ `facing`
（我们自己的动作历史推的）→ `place.step_toward(facing)`。两个输入都是确定
量，所以这条记忆的键是确定的。

**完整分支逻辑**（对照代码）：

```python
facing = BUTTON_FACING.get(action.name, before.facts.get("facing", ""))
if not facing or before.place is None or after.place is None:
    return []

ahead = before.place.step_toward(facing)
key_desc = f"x={before.place.x} y={before.place.y}→{action.name}"
```

第一步先算 `facing`：如果 `action.name` 是方向键，`BUTTON_FACING` 能直接查出
按这次键会朝向哪个方向——**用的是这一次按键决定的朝向**；否则（比如 `a` 键）
用 `before.facts.get("facing", "")`，即**执行前**已知的朝向。docstring 特别
强调这个区别不能反：`before.facts["facing"]` 是走这一步**之前**的朝向，方向
键要用它去算"我走到了哪格"会指向完全无关的一格；而 `a` 相反，它作用在**当前**
朝向上，所以用 `before` 的那个是对的。

若 `facing` 算不出（开局、过场之后朝向未知）、或 `before.place`/`after.place`
任一为 `None`，直接返回 `[]`——**朝向未知时宁可不记也不能记错格子**。

否则算出 `ahead = before.place.step_toward(facing)`（面朝的那一格坐标）和
`key_desc`（"x=.. y=..→按键名" 的姿势描述字符串）。

**分支一：`action.name == INTERACT_KEY`（按 `a` / 交互键）**

```python
if action.name == INTERACT_KEY:
    kind = self._kind_at(before, ahead)
    if kind is None:
        return []
    text = after.facts.get("dialog_text", "")
    fact = self._objects.touch(ahead, kind, text)
    self._objects.record_attempt(
        ahead, kind, key_desc, RESULT_DIALOG if text.strip() else RESULT_NONE
    )
    return [fact]
```

- 用 `_kind_at(before, ahead)` 判断面朝的那一格是什么。若 `kind is None`
  （面朝的不是人/招牌/门，对着空地按 `a` 什么也不会发生），**不记**，返回
  `[]`。
- 否则取 `after.facts["dialog_text"]`（交互后弹出的对话文本，缺省空串），
  调 `self._objects.touch(ahead, kind, text)` 建档/取档并记一句话，再调
  `record_attempt` 记一次尝试：结果是 `RESULT_DIALOG`（有对话文本）或
  `RESULT_NONE`（没有）。
- 返回 `[fact]`（`touch()` 的返回值，被更新的那条 `ObjectFact`）。

**分支二：方向键**

```python
if action.args.get("times", "1") != "1":
    return []
moved = self._outcome(before, after, facing)
if not moved:
    return []
```

- **连按方向键（`times > 1`）跳过**：`action.args["times"]` 不等于 `"1"` 时
  直接返回 `[]`。理由：中途经过哪些格子算不出来，结果挂不到确定的一格上。
- 调 `_outcome(before, after, facing)`（见 3.3.5 节）算出这一步的结果字符串
  （`"warp"`/`"moved"`/`"stay"`/`""`）。若为空串（算不准，包括"原地转身"的
  情况，见下），返回 `[]`。

```python
candidates = [
    (place, self._kind_at(before, place))
    for place in surrounding_cells(before.place)
]
known = [kind for _, kind in candidates if kind is not None]
changed = before.place.map_id != after.place.map_id
if changed and len(known) > 1:
    return []

result = f"{RESULT_WARP_PREFIX}{after.place.map_id}" if changed else RESULT_NONE
touched: list[ObjectFact] = []
for place, kind in candidates:
    if kind is None:
        continue
    touched.append(self._objects.record_attempt(place, kind, key_desc, result))
return touched
```

- 用 `surrounding_cells(before.place)`（`memory/util.py`）枚举**脚下 + 周围
  一圈**的候选格子，对每格调 `_kind_at(before, place)` 得到该格是什么
  （或 `None`）。docstring 解释为什么不只查面朝的 `ahead` 一格：这一次按键
  可能碰到的候选不只是 `ahead`——**脚下这格尤其要留**，人物精灵盖住了它，
  当帧的 `landmarks` 已经不再报告那里有扇门（踩在门上朝外按是室内出口
  唯一的走法）。
- `known` 是所有非 `None` 的候选种类列表；`changed` 表示这一步是否换了地图
  （`before.place.map_id != after.place.map_id`）。
- **两个候选同时存在且换了图（`changed and len(known) > 1`）时整步作废**，
  返回 `[]`——算不出是哪一个把地图换掉的。
- 否则算出统一的 `result`：换图则是 `RESULT_WARP_PREFIX + after.place.map_id`
  （即 `warp:<map_id>` 一类字符串），没换图则是 `RESULT_NONE`。
- 遍历全部候选，跳过 `kind is None` 的格子，对其余每格调
  `record_attempt(place, kind, key_desc, result)`，把返回的 `ObjectFact`
  收进 `touched` 列表，最终整体返回。

**关于"原地转身"这条不记的规则**，体现在 `_outcome` 里（见 3.3.5）：宝可梦里
朝向不同时按方向键，第一帧只转向不移动，所以只有**本来就朝着那个方向**时
才把 `RESULT_NONE` 记下来；否则 `_outcome` 返回空串，`note_step` 在
`if not moved: return []` 处直接短路，不落入后面的候选枚举逻辑。

**`note_step` 完整的"什么情况下不记"清单**（源自其 docstring）：

1. 面朝的不是人/招牌/门：对着空地按 `a` 什么也不会发生。
2. 朝向未知（开局、过场之后）：算不出面朝哪一格，宁可不记也不能记错格子。
3. **连按方向键**（`times > 1`）：中途经过哪些格子算不出来，结果挂不到确定
   的一格上。
4. **原地转身**：只有本来就朝着那个方向时才把 `RESULT_NONE` 记下来。
5. **两个候选同时存在且换了图**：算不出是哪一个把地图换掉的，整步作废。

#### 3.3.5 `_kind_at(obs: Observation, place: Place) -> str | None`

```python
def _kind_at(self, obs: Observation, place: Place) -> str | None:
    kind = kind_in_frame(obs, place, INTERACTIVE)
    if kind is not None:
        return kind
    fact = self._objects.query(place)
    if fact is not None and fact.landmark.kind in INTERACTIVE:
        return fact.landmark.kind
    return None
```

先查**当帧 `landmarks`**（`kind_in_frame(obs, place, INTERACTIVE)`，来自
`memory/util.py`，只在 `INTERACTIVE` 范围内匹配）；若认不出（`None`），再查
**语义记忆**（`self._objects.query(place)`），如果查到的条目的 `landmark.kind`
属于 `INTERACTIVE`，则用它兜底；否则返回 `None`。

两个来源不是冗余：`landmarks` 是内存给的当帧真相，但它**看不见被主角踩住的
那一格**（人物精灵挡住）；语义记忆里存的是"我以前见过那里有什么"，正好补上
这个盲区。

#### 3.3.6 `_outcome(before, after, facing) -> str`（静态方法）

```python
@staticmethod
def _outcome(before: Observation, after: Observation, facing: str) -> str:
    assert before.place is not None and after.place is not None
    if after.place.map_id != before.place.map_id:
        return "warp"
    if (after.place.x, after.place.y) != (before.place.x, before.place.y):
        return "moved"
    if before.facts.get("facing", "") == facing:
        return "stay"
    return ""
```

这一步动没动，判定顺序：

1. `map_id` 变了 → `"warp"`。
2. `map_id` 没变但坐标 `(x, y)` 变了 → `"moved"`。
3. `map_id`、坐标都没变，且**执行前的朝向本来就等于这次按键的朝向**
   （`before.facts["facing"] == facing`）→ `"stay"`（真的原地不动，没有效果）。
4. 否则（坐标没变，但执行前朝向 ≠ 这次按键方向——即这一按只是**转身**，
   不是撞墙）→ 返回空串 `""`，表示算不准，`note_step` 据此不记录。

前置断言：`before.place is not None and after.place is not None`（调用方已经
在 `note_step` 里检查过）。

docstring 记录了一个真实踩过的坑：早一版这里返回的是给模型看的字，那句字是
"过去了"（表示撞墙无效），实测直接把 agent 卡死——它站在 `x=2 y=7` 的门上，
档案写着「站在上面按right→过去了」，于是按 right 走到 `x=3 y=7` 的另一扇门
上，那扇门也写着「站在上面按left→过去了」，于是按 left 走回去，**两格之间
来回踱步**。现在这个歧义在**渲染层**解决：门的成功判据是固定的
（`map_id` 变了），所以 `ObjectFact.leads_to` 直接把"哪次尝试换了图"算出来，
剩下的一律归进 `RESULT_NONE`；`_outcome` 这里只要如实报"动没动"就够了。全部
来自两个 `place` 相减——**没有一个字是模型说的**。

### 3.4 通用先验（`knowledge_base`）

```python
def knowledge_base(self) -> str:
    return _load_knowledge_base()  # pokemon_agent.memory.knowledge.store.load_all
```

第二类语义记忆，和 3.3 节的 `object` 类（按坐标存取）**不共用存储**——直接转发
`memory/knowledge/store.py` 的 `load_all()`，`MemoryTool` 这一层不做任何编排，
因为这类知识没有"一次按键该查哪几格候选"这种游戏规则性质的判断要做，
读端只是原样转发。

**不缓存，每次调用都重新读盘**：这里没有像 `_episodes`/`_objects` 那样的实例
字段存一份 `knowledge`，构造函数也没有多收一个参数——`__init__` 完全不变。
这是刻意的：知识库是要**运营**的东西，要能一边跑着 episode 一边改
`memory/knowledge/*.md` 文件、不重启进程就生效；缓存在构造时读一次的话，
中途改了文件也影响不到正在跑的这一局。每一步一次磁盘读、个位数小文件，
这个代价完全可以接受。

消费方：`Harness._retrieve_memory()`（不是 `_observe()`），和 `known_here()`
的结果一起折进 `obs.facts`，见 `harness/SPEC.md` 4.5 节。

---

## 4. Port 方法签名总表

### 4.1 `GameToolPort`（`GameTools` 实现）

| 方法 | 签名 | 要点 |
|---|---|---|
| `perceive` | `() -> PerceptionResult` | 幂等只读，帧内缓存不产生额外模型调用；不写 trace、不推进世界、不触发判定 |
| `inspect` | `(focus: str) -> PerceptionResult` | 前置：`focus` 非空；世界不推进；不抛异常，问不出来就写"没看清" |
| `get_action_space` | `() -> ActionSpace` | 后置：`names` 非空；`intents` 不在此层填 |
| `execute` | `(action: Action) -> ToolResult` | 前置：`action.name` 属于调用前最近一次 `get_action_space()` 的结果，需 assert；后置：`result.observation` 非空 |
| `reset` | `(task: Task) -> PerceptionResult` | 前置：`task.max_steps > 0`；后置：`observation.done` 为 False |
| `last_frame_sha`（property） | `-> str` | 最近一次观测所依据帧的哈希；无"帧"概念的实现返回空串 |

### 4.2 `MemoryToolPort`（`MemoryTool` 实现）

| 方法 | 签名 | 要点 |
|---|---|---|
| `query_episodic` | `(query: str, limit: int = 5) -> list[MemoryEntry]` | 前置：`limit > 0`；后置：条数 ≤ limit，按相关性降序；检索策略属于实现方 |
| `recent` | `(episode_id: str, limit: int) -> list[MemoryEntry]` | 前置：`limit > 0`；后置：条数 ≤ limit，全部来自该 episode，最新在最后 |
| `write_episodic` | `(entry: MemoryEntry) -> None` | 前置：`entry.rationale` 非空 |
| `episodic_size`（property） | `-> int` | 库里情景记忆条数；A/B 实验自变量 |
| `known_here` | `(obs: Observation) -> str` | 后置：`obs.place` 为 None 或无已知条目时返回空串 |
| `knowledge_base` | `() -> str` | 和坐标无关的通用先验；不筛选，全部拼接；每次调用重新读盘，不缓存；库为空返回空串 |
| `see_objects` | `(obs: Observation, stamp: str) -> None` | 前置：一步只调一次，`stamp` 非空 |
| `note_step` | `(before: Observation, action: Action, after: Observation) -> list[ObjectFact]` | 前置：`before`/`after` 都有 `place`；算不出确定格子时不记，宁可漏记不可记错 |

（以上签名与前置/后置条件汇总自 `interfaces/tools.py`；因为这是 `GameTools`/
`MemoryTool` 两个类的对外契约，本文件重复列出以便与上文的实现细节对照阅读。）

---

## 5. 与 `memory/` 包、`world/` 包的关系（组合关系）

- **`GameTools` 组合 `WorldPort`**：构造函数持有一个 `world: WorldPort` 字段
  （`self._world`），是纯粹的组合关系——`GameTools` 不了解 `world/` 包内部
  实现（当前唯一实现是 `PyBoyWorld`），只通过 `WorldPort` 协议交互
  （`reset`/`observe`/`inspect`/`all_actions`/`last_frame_sha`/`step`）。
  `interfaces/world.py` 明确指出：`GameToolPort` 是"Harness 能拿世界做什么"，
  `WorldPort` 是"世界本身能做什么"，两者职责不同且变化速度不同；换模拟器时
  **`GameToolPort` 和大脑一行都不用改**——这就是分层的收益。掩码这类策略
  不在 `WorldPort` 里：世界只回答"全部动作是什么"和"执行这个动作会怎样"，
  masking 是 harness（即 `GameTools.get_action_space()`）的策略。

- **`MemoryTool` 组合 `SemanticObjectStore`（并直接持有情景记忆列表）**：
  构造函数持有 `self._objects: SemanticObjectStore`（默认 `ObjectMemory()`，
  可注入其他实现），是通过协议类型标注实现的组合，`memory/port.py` 明确这是
  "底层协议，不是大脑看到的接口"：大脑连"语义记忆"这个词都不该知道；
  `MemoryTool` 组合这个协议、翻译成 Harness 能用的方法，
  `interfaces/tools.py` 的 `MemoryToolPort` 才是 Harness 真正认识的那一层。
  情景记忆（`self._episodes: list[MemoryEntry]`）则没有额外协议层，直接是
  `MemoryTool` 自己管理的列表。

- **`MemoryTool.knowledge_base()` 直接转发 `memory/knowledge/store.py` 的
  `load_all()`**，不经过 `SemanticObjectStore`、不经过任何协议层——`MemoryTool`
  这一侧没有为它多存一个字段，每次调用都是一次直接的函数调用 + 磁盘读。这类
  记忆没有编排逻辑要做，`port.py` 那套 Reader/Writer/Store 三件套对它是过度设计。

- **Harness 是组合两者的地方**：`Harness.__init__` 收 `game: GameToolPort` 和
  `memory: MemoryToolPort` 两个独立参数；`facts["known_objects"]` 这类需要
  同时用到世界观测和语义记忆的信息，由 `Harness._observe()` 先调
  `game.perceive()` 拿到 `Observation`，再调 `memory.known_here(obs)` 拼接，
  两个协议各管各的，跨协议的组合逻辑全部留在 Harness 一层，`GameTools` 与
  `MemoryTool` 彼此互不知道对方的存在。
