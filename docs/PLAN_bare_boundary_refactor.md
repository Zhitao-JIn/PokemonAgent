# 计划：模块彻底解耦 + schemas → communication

**状态：A/B/C/D 四个问题已由用户确认（A=彻底裸字段化；B=domain 类型也不带
For/From 后缀；C=datastore；D=TraceEvent 一并搬）。第一步（world）已完成并提交
（见 CHANGELOG "2026-09-11（12）"）。

**（12）条对 memory 的处理有一处错误，已在 (13) 条修正**：`StepMemory`/
`EpisodeMemory`/`ObjectFactEvent` **不该**搬进 `pokemon_agent/memory/`——
`MemoryStorePort` 完全不透明（只收发裸字段/dict），不像 `TracePort` 那样真的
需要在内部构造/解析这几个类，所以它们物理上留在/搬回 `schemas/memory/`；
`StepMemory`/`ObjectFactEvent` 对 `world.Observation`/`PlaceInWorld` 的引用
改成了各自的内部类（`StepMemory.Observation`、`ObjectFactEventBase.Place`），
组装方（`brain.brain.py::reflect()`、`harness/object_interactions.py`）负责
转换。`trace/datastore/`（`TraceEvent`）不受影响——它是被套用同一条规则时
唯一判断正确的一例。详见 CHANGELOG "2026-09-11（13）"。

**判断一个数据形状该不该归某个模块自己的准确标准**（这次教训之后收敛出来的）：
只有当该模块自己的 Port/实现**真的需要构造或消费它的具体样子**时，才归它——
`TracePort.append()`/`LocalTrace.read_disk_events()` 满足，`MemoryStorePort`
不满足。

第二步起（memory 的 `world.Observation`/`PlaceInWorld` 引用已随 (13) 条一并
处理；trace/providers/brain/tools 各自的零依赖化）待续。**

## 0. 背景

上一轮（本次会话内已完成、已提交 `caca742`~`b1a3b87`）把 `pokemon_agent/interfaces/`
这个集中注册表撤销了：每个模块的 Protocol port 搬回自己模块下的 `interface/`
（或 `ports.py`）。搬完之后我们才发现更根本的问题——搬完的 port 方法本身还是长
这样：

```python
def choose_once(self, req: ChooseOnceReq) -> ChooseOnceResp: ...
```

`ChooseOnceReq`/`ChooseOnceResp` 是 `schemas.brain` 里的信封，`brain/interface/
brain_port.py` 因此依然要 `from pokemon_agent.schemas.brain import ...`、
`from pokemon_agent.schemas.memory import StepMemory`。信封本身又经常引用别的
模块的 domain 类型（比如 `ChooseOnceReq` 大概率带 `ObservationFromWorld`）。这就是
上一轮反复出现"循环导入"的根因——不是真的有双向架构依赖，是"A 的信封提到 B 的
domain 类型，B 又要用 A 的 port"这种链路在 Python 的包初始化模型下很容易兜圈子。

你指出的解法更彻底，不是继续修修补补：

> 都不行，只有 tool 层需要 schemas 的东西。schemas 层里只留信封，所以 memory 的
> store 也要移动到对应的 memory 模块，world 的也要移动进 world……原则是模块间
> 完全没有相互依赖，也没有信封，只靠裸函数和 tool 层交互，schemas 层只留
> communication，全部移出后，把 schemas 改名为 communication。

即：

1. **brain / world / memory / trace / providers 这几个领域模块之间，以及它们与
   `schemas.*` 之间，零依赖。** 谁都不 import 别人的 domain 类型，也不 import
   任何信封。
2. **每个领域模块的 port 方法签名改成裸字段**（原始类型 / 该模块自己的 dataclass、
   不是 pydantic 信封），不再收发 `*Req`/`*Resp`。
3. **信封的组装/拆解全部收归 tool 层**（`BrainTool`/`GameTools`/`MemoryTool`/
   `TraceTool`）——tool 层本来就是唯一被允许认识多个模块的地方。
4. **之前说好但没做完的两块搬家，这次一并做：**
   - `schemas/memory/datastore/{episode_memory,object_memory,step_memory}.py`
     → 搬进 `pokemon_agent/memory/`。
   - `schemas/world/domain/{action_semantics,action_space_for_brain,
     observation_from_world,place_in_world,screen_model}.py` → 搬进
     `pokemon_agent/world/`。
5. 顺带确认：`schemas/trace/datastore/trace_event.py`（`TraceEvent`）按同一原则
   也要搬进 `pokemon_agent/trace/`——虽然你这次没点名，但它和 memory/world 的
   datastore 文件是同一种"領域数据躺在 schemas 里"的情况，符合"schemas 只留信封"
   这条总原则，计划里一并处理，等你确认。
6. 全部搬完之后，`pokemon_agent/schemas/` 改名成 `pokemon_agent/communication/`。

## 1. 现状盘点（`pokemon_agent/schemas/` 当前内容）

```
schemas/brain/communication/*        10 个信封（ChooseOnceReq/Resp 等）—— 已经是纯信封，不用动
schemas/frontend/communication/*     纯信封 —— 不用动
schemas/harness/communication/*      一大堆 From*To* 信封 —— 纯信封，不用动
schemas/memory/__init__.py
schemas/memory/communication/__init__.py   （目前是空的/占位）
schemas/memory/datastore/
    __init__.py
    episode_memory.py     EpisodeSummaryRecord 之类 —— 要搬进 memory/
    object_memory.py      ObjectFactEvent —— 要搬进 memory/
    step_memory.py        StepMemory —— 要搬进 memory/（依赖 schemas.world.ObservationFromWorld）
schemas/providers/communication/*    LlmCompleteReq/Resp、VisionDescribeReq/Resp —— 纯信封，不用动
schemas/trace/
    __init__.py
    datastore/trace_event.py         TraceEvent —— 要搬进 trace/
schemas/world/
    communication/PerceiveOnceResp.py   信封 —— 不用动
    domain/
        __init__.py
        action_semantics.py          FACING_STEP 等 —— 要搬进 world/
        action_space_for_brain.py    ActionSpaceForBrain —— 要搬进 world/
        observation_from_world.py    ObservationFromWorld —— 要搬进 world/
        place_in_world.py            PlaceInWorld/LandmarkInWorld —— 要搬进 world/
        screen_model.py              Scene/Overlay 等 —— 要搬进 world/
```

**这次搬家和上一轮"interfaces 撤销"是同一手法**：`git mv` 物理搬过去、原地留
docstring 说明搬去哪了，`schemas/<module>/__init__.py` 只剩纯信封的 re-export、
`CHANGELOG.md` 记一笔。区别是这次不是"port 挪窝"，而是"port 的方法签名本身要变"。

## 2. Port 签名怎么裸字段化 —— 以 `BrainPort` 为例

现状（`brain/interface/brain_port.py`）：

```python
def choose_once(self, req: ChooseOnceReq) -> ChooseOnceResp: ...
def judge(self, req: JudgeReq) -> JudgeResp: ...
def reflect(self, req: ReflectReq) -> StepMemory: ...
def plan_once(self, req: PlanOnceReq) -> PlanOnceResp: ...
def verify_and_summarize(self, req: VerifyAndSummarizeReq) -> VerifyAndSummarizeResp: ...
```

每个 Req/Resp 拆开看，字段分两类：

- **纯标量/字符串**（`prompt: str`、`entries` 的条数等）——直接变成裸参数，没有
  争议。
- **富结构字段**（`ChooseOnceReq.space: ActionSpaceForBrain`、
  `ChooseOnceResp.recalled`、`ReflectReq` 里的两帧 `ObservationFromWorld`……）——
  这些本来就是 **world 的 domain 类型**，不是"brain 与 harness 之间的信封"。
  按你确认过的原则（"跨层的数据形状不用提到 from，依旧放 domain 里；只有信封
  需要 from/to"），这些类型**搬进 world/ 之后原地保留**，brain 的方法签名照样
  可以用 `ObservationFromWorld`/`ActionSpaceForBrain` 做参数类型——**只要 brain
  import 的是 `pokemon_agent.world.XXX`，而不是 `pokemon_agent.schemas.xxx`，
  这就已经不算"依赖 schemas"了。**

  ⚠️ 这里有个和"模块间零依赖"字面冲突的地方，需要你确认（见第 5 节问题 B）：
  `brain` 的方法要用到 `ObservationFromWorld`，如果这也算"brain 依赖 world"，
  那就是真正的模块间依赖而不只是"依赖 schemas"，需要另一层解法（比如这些跨模块
  会用到的 domain 类型专门放一个大家都能 import 的"公共 domain 层"，但那样又会
  变成新的"schemas"）。下面先给出两种候选方案，等你选：

  **方案 A（保守，先修复"依赖 schemas"，不动"依赖别的领域模块"）**：
  `ObservationFromWorld`/`ActionSpaceForBrain`/`PlaceInWorld` 等**跨模块公用的
  domain 形状**搬进 `world/`，brain（以及 tools、harness）继续像现在一样直接
  `from pokemon_agent.world import ObservationFromWorld` 使用它们——brain 依赖
  world 的 domain 类型，但不再依赖任何 `schemas.*`。这满足"只有 tool 层需要
  schemas"，但不完全满足"模块间完全没有相互依赖"（brain 依然 import 了 world
  的类型）。

  **方案 B（彻底裸字段化）**：`choose_once` 等方法的入参**逐字段展开成原始类型
  / 该方法自己的轻量 dataclass**（不是 pydantic、不放共享包），例如：

  ```python
  def choose_once(
      self,
      prompt: str,
      *,
      action_names: tuple[str, ...],
      # ObservationFromWorld 拆开传，或者只传 brain 真正用得到的那几个字段
  ) -> ChooseOnceResult:  # ChooseOnceResult 是 brain 自己定义的、只給 brain 用的返回形状
      ...
  ```
  `ChooseOnceResult` 这类"这个方法专属的返回值"由 **brain 自己定义**（brain 拥有
  它，不是共享类型），tool 层负责把它转换成 harness 需要的信封。这样才是真正的
  "模块间零依赖，只靠裸函数和 tool 层交互"——但代价是像 `ObservationFromWorld`
  这种本来就有十几个字段、还有 `render()`/`stall_key()` 方法的类，要么被拆散成
  一堆裸参数（`choose_once` 的参数列表会变得很长），要么 brain 自己重新定义一个
  跟 world 的 `ObservationFromWorld` 结构近似但字段更少的"brain 眼中的观测"类型
  （复制一份、不共享类）。

  我倾向 A，理由：A 已经消灭了"schemas 信封"这个循环导入的根因（信封本来就是
  causing circular import 的东西——它经常需要反向引用），"brain 依赖 world 的
  domain 类型"是单向的、不会兜圈子，工程上代价也小很多；B 更纯粹但要么参数列表
  爆炸要么产生重复类型定义，性价比存疑。但这是你的架构决定，需要你明确选 A/B/
  还是别的方案（比如 B 但只拆最关键的几个字段，其余仍传一个 world 的类型）。

## 3. tool 层承接的职责

以 `BrainTool.choose_once`（举例，具体方法名待核实现状）为例，改造后大致是：

```python
class BrainTool:
    def choose_once(self, req: FromHarnessToBrainToolChooseOnceReq) -> FromBrainToolToHarnessChooseOnceResp:
        # 1) 拆信封：从 req 里取出 brain.choose_once 需要的裸参数
        result = self._brain.choose_once(prompt=..., action_names=...)
        # 2) 拼信封：把 brain 返回的裸结果包回 harness 认识的 Resp
        return FromBrainToolToHarnessChooseOnceResp(...)
```

也就是说，`schemas.harness` 里那批 `From*To*` 信封（harness ↔ tool 层之间）
**保持不变**——那些本来就是"信封"，一直被你认可（"只有信封需要 from，to"）。
唯一变化的是 **tool 层往下一层（brain/world/memory/trace/providers）**这段，
从"转发信封"变成"拆信封 → 调裸函数 → 拼信封"。

## 4. 各模块目标结构

```
pokemon_agent/memory/
    ...现有实现文件...
    datastore/ 或 records/          # 具体子目录名待定，见问题 C
        step_memory.py              # 从 schemas/memory/datastore/ 搬来
        episode_memory.py
        object_memory.py

pokemon_agent/trace/
    ...现有实现文件...
    trace_event.py                  # 从 schemas/trace/datastore/ 搬来（是否需要
                                     # 单独子目录，还是直接放 trace/ 顶层，见问题 C）

pokemon_agent/world/
    interface/
        domain/
            facts.py                 # 已在（本次会话更早步骤搬的）
            screen_state.py          # 已在
            terrain_map_from_ram.py  # 已在
            action_semantics.py      # 新搬入
            action_space_for_brain.py  # 新搬入
            observation_from_world.py  # 新搬入
            place_in_world.py          # 新搬入
            screen_model.py            # 新搬入（Scene/Overlay/terrain_legend）
        world_port.py                 # 方法签名裸字段化（若选方案 A，仍可用这些
                                       # domain 类型做参数/返回值类型）
```

`brain/`、`providers/` 的 `interface/` 目录结构不变，变化只在 `interface/*_port.py`
里各方法的签名（改成裸参数）和 import（不再 `from pokemon_agent.schemas.*`）。

`schemas/` 瘦身后只剩：

```
pokemon_agent/schemas/  →  改名为 pokemon_agent/communication/
    brain/communication/*
    frontend/communication/*
    harness/communication/*
    providers/communication/*
    world/communication/PerceiveOnceResp.py
```

（`schemas/memory/`、`schemas/trace/` 整个目录清空后按需删除或保留一个空
`communication/` 占位——取决于这两个模块未来是否会有信封，如果暂时没有就直接
不建这两个子目录。）

## 5. 需要你确认的问题

**A. 方案 A vs 方案 B**（见第 2 节）：brain 等领域模块之间要不要允许直接 import
彼此的 domain 类型（比如 brain import world 的 `ObservationFromWorld`）？
我推荐方案 A（domain 类型互相可以单向依赖，只是不能有信封、不能有反向依赖），
但你说的"模块间完全没有相互依赖"如果是字面意思，就要选方案 B（彻底裸字段化，
brain 自己复制/精简一份需要的字段）。

**B.**"而且也不用 for"这半句——我没看懂具体指什么，猜测可能是：
  - 打字打到一半漏字（比如想说"也不用 from/to 命名"，但这条你已经在上一句说过
    了——"只有信封需要 from，to"）；
  - 或者指某个具体命名/写法里不需要再用 `for`（比如某个类型名里的 `ActionSpace
    ForBrain` 这种 "For" 后缀，是不是也要去掉，跟"domain 里不需要 from/to"一样
    "domain 里也不需要 For"？）

  如果是后者：`ActionSpaceForBrain`、`ObservationFromWorld`、
  `TerrainMapFromRam` 这几个名字目前都带方向性后缀（`ForBrain`/`FromWorld`/
  `FromRam`），如果"domain 类型不需要方向性命名"，这几个是不是也要改成中性名
  （比如 `ActionSpace`、`Observation`、`TerrainMap`）？这是一笔不小的改名，需要
  你明确点头才会做。

**C. memory/trace 搬进去的子目录名**：`step_memory.py`/`episode_memory.py`/
`object_memory.py` 放 `memory/datastore/`、`memory/records/` 还是直接摊平在
`memory/` 顶层？`trace_event.py` 放 `trace/` 顶层还是新开子目录？（这在本次会话
更早之前就悬而未决，这次一起定下来。）

**D. `TraceEvent` 是否一并搬**：你这次只点名了 memory 和 world，没提 trace——按
"schemas 只留信封"的总原则我认为 `schemas/trace/datastore/trace_event.py` 也该
搬进 `pokemon_agent/trace/`，计划里包含了这一步，但想让你明确认可，不是我自己
延伸解读走偏。

## 6. 执行顺序（沿用"接口先行"迁移的老办法：leaf 优先、一个模块一个 commit）

1. **world**：`schemas/world/domain/*` 搬进 `world/interface/domain/`；
   `world_port.py` 签名裸字段化（先做，因为它是被依赖最多的一层，其余模块都要
   跟着改 import）。
2. **memory**：`schemas/memory/datastore/*` 搬进 `memory/`；`memory` 的 port
   （`ports.py`）签名裸字段化。
3. **trace**：`schemas/trace/datastore/trace_event.py` 搬进 `trace/`；trace 的
   port 签名裸字段化（如果问题 D 确认要做）。
4. **providers**：port 签名裸字段化（providers 目前应该已经比较接近裸字段，
   需要核实）。
5. **brain**：`brain_port.py` 签名裸字段化（依赖第 1、2 步先完成，因为它要用到
   `ObservationFromWorld`/`StepMemory` 的新位置）。
6. **tools**：`BrainTool`/`GameTools`/`MemoryTool`/`TraceTool` 承接信封拆装职责
   （依赖前面所有 port 签名已经改完）。
7. **收尾**：`schemas/` 改名 `communication/`，全仓库 import 路径替换，
   `pokemon_agent/schemas` 这个名字从代码库消失；`CLAUDE.md`/`CHANGELOG.md` 收尾。

每一步继续沿用这次迁移验证过的方法：`git mv` 保留历史、CRLF 文件用字节安全的
方式改、用 pydantic/langgraph/rank_bm25 stub 跑多种 import 顺序验证、每步一个
commit + CHANGELOG 条目。

## 7. 不在这份计划范围内、但顺带会碰到的东西

- `schemas/frontend/`：看起来已经是纯信封，本计划不动它，除非改名 communication
  时需要跟着挪路径。
- `pokemon_agent/build.py`、`api.py` 等顶层入口：只要跟着各模块的新 import 路径
  改，不涉及架构决策。

---

**在你回答 A/B/C/D 四个问题之前，我不会动任何代码。** 如果你觉得上面对"裸函数"
的两种方案理解都不对，也请直接说你设想中 `choose_once` 之类方法改完之后大概
长什么样，我再据此调整方案。
