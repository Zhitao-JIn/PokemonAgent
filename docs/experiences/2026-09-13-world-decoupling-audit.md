# world 模块脱钩审计：按 P1～P7 清点「如何移出」

- 日期：2026-09-13
- 判据来源：`docs/experiences/2026-09-13-brain-decoupling-principles.md`（P1～P7）
- 关联铁律：`AGENTS.md` 第 2 条（四模块各自只暴露一个 Port，按独立第三方对待）
- 系统状态：**world 是四模块里唯一「出边不为零」的一个**——2 条对外依赖
  （1 条真违规、1 条 P3 例外），22 条入边里 **16 条非 tool**。
  与 brain / memory / trace 三者的终态**不同级**。
- 验证环境：`C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe`
  （managed 3.13 与仓库内 `.venv` 同 memory 审计的坑，见 §9）
- **未跑真实 harness**（按项目规矩由用户自行运行）；未发真实 API 请求

---

## 零、两个断言的结论：**两半都不成立，且原因不同**

用户问的是「world 无对外依赖 + 外部只有 tool 对其依赖」。**这两个断言现状都是否**，
但**堵点的性质完全不同**，必须分开说：

| 断言 | 结论 | 精度 | 堵在哪 |
|---|---|---|---|
| world **无对外依赖**（出边 = 0） | ❌ **不成立** | 2 条出边 | ① `pyboy_world.py:26` → `tools.prompts`（**真违规、反向依赖**）② `errors.py:24` → `errors.AgentError`（P3 判据下「该继承」） |
| world **仅被 tool 依赖**（入边 ⊆ tool） | ❌ **不成立** | 22 条入边，**16 条非 tool** | 实现依赖 1 条（`build.py`）+ 形状引用 14 条 + 异常引用 1 条 |

**三条必须先说清的事实**：

1. **`import pokemon_agent.world` 本身是干净的**——拉起 17 个模块，
   **全是 `world.*` 自己**（16 个子模块 + 包自身），零兄弟模块。
   出边全藏在**懒加载的子模块**里（P7 的 `__getattr__` 把出边盖住了）。
2. **但 world 的核心实现拖不动**：`import pokemon_agent.world.pyboy_world`
   会拉起 **102 个 `pokemon_agent.*` 模块，其中 82 个不是 world 的**
   （brain 17 / schemas 54 / tools 4 / harness 4 / config 1 / errors 1）。
   **这是四模块里最脏的一个数字**（对照：`import pokemon_agent.memory` 的外部拉起 = 0）。
3. **出边的 2 条里，真正致命的是 `tools.prompts` 那条**——它不只是"多一个依赖"，
   它是**反向依赖**：tools 本来就依赖 world（`game_tools.py` 收 `WorldPort`），
   world 又回头依赖 `tools.prompts`，**模块图上是一条真实的环**（§1.3）。
   `AgentError` 那条反而是**可以辩护的例外**（P3 明文写着 world 该继承）。

---

## 一、P1 落地：world 拷得走吗 —— 出边 AST 审计（2 条）

### 1.1 附 A：逐文件核对（19 个 py 文件）

AST 全树扫描（含函数内 import、标出 `TYPE_CHECKING`）：

```
pokemon_agent/world/__init__.py              → pokemon_agent.world.interface          [包内自指]
pokemon_agent/world/errors.py                → pokemon_agent.errors                   [★ 外部依赖] L24
pokemon_agent/world/frame_slot.py            → (无)
pokemon_agent/world/pyboy_world.py           → pokemon_agent.tools.prompts            [★ 外部依赖] L26
                                             → pokemon_agent.world{,.errors,.frame_slot,.interface,.ram}  [包内自指]
pokemon_agent/world/ram.py                   → pokemon_agent.world.interface          [包内自指]
pokemon_agent/world/interface/__init__.py    → world.interface.domain{,.memory,.vision_provider,.world_port}  [包内自指]
pokemon_agent/world/interface/memory.py      → (无，只有 typing.Protocol)
pokemon_agent/world/interface/vision_provider.py → world.interface.domain.vision_describe  [包内自指]
pokemon_agent/world/interface/world_port.py  → world.interface.domain                 [包内自指]
pokemon_agent/world/interface/domain/__init__.py → 9 个子文件                       [包内自指]
pokemon_agent/world/interface/domain/*.py    → 同包内互相引用 / 无                    [包内自指]
```

**逐层核对表**：

| 层 | 文件 | 对外（兄弟模块）依赖 | 第三方/标准库 |
|---|---|---|---|
| 协议 + 形状 | `world/interface/**`（10 个文件） | **0** | `pydantic` / `typing` / `__future__` |
| 实现的工具件 | `frame_slot.py` / `ram.py` | **0** | `dataclasses` / `enum` / `typing` |
| 实现的粘合层 | `pyboy_world.py` | **1（★ tools.prompts）** | `pyboy` / `PIL` / `base64` / `io` / … |
| 内部词汇 | `errors.py` | **1（★ pokemon_agent.errors）** | `__future__` |

**包外兄弟依赖总数 = 2。**

### 1.2 两条出边分别定性

#### ★ 违规一：`pyboy_world.py:26` —— world → tools（反向依赖）

```python
from pokemon_agent.tools.prompts import load as load_prompt   # L26
...
self._prompt = load_prompt(prompt_name)                       # L192
prompt = self._prompt.render(known_map=terrain.render(), terrain_legend=terrain_legend())  # L353
```

**为什么这是真违规，而不是"用了个 prompt 工具"**：

- `tools/` 是**桥层**——它的存在意义是"被 harness 依赖、去依赖各模块"。
  `world → tools` 把方向掉了个头，`tools` 于是同时是 world 的上游和下游。
- 它**违反了 P1 的唯一判据**：「把 `world/` 拷进另一个项目，感知还跑得起来吗」
  —— **跑不起来**，`PyBoyWorld.__init__` 第一句就 `ImportError`。
- 它也是**唯一一条能靠既有原则直接判死刑的出边**——不需要任何新判据。

**而正确的归属早就写在 `tools/prompts/__init__.py` 的 docstring 里**（作者自己承认了）：

> `perceive_screen` 没有配 `.py`：它不经过 `Brain` 也不经过任何 Harness 节点
> ——**`PyBoyWorld` 自己 `load()` 并渲染，是"拥有这次 LLM 调用的那个类"自己的事**。

**"拥有这次调用的类"就是权威判据**。这次 LLM 调用属于 world，所以它的
**素材（prompt）该跟 world 走**——这正是 P2 第二类（内部词汇）在 prompt 上的展开：
`tools/prompts/` 的另外三份（`decide_action`/`judge_success`/`run_plan`/
`verify_and_summarize`）由 harness/brain 的链路消费，留在 tools 是对的；
只有 `perceive_screen.md` 的消费者在 world 里，它才是"错放的第三份"。

#### ✅（可辩护的）例外：`errors.py:24` —— world → `AgentError`

```python
from pokemon_agent.errors import AgentError    # L24
class PerceptionAttemptFailed(AgentError): ...  # L27
class PerceptionFailure(AgentError): ...        # L44
```

**这一条不是疏漏，是 P3 判据的明文结论**：

> `world` 的异常 → `perceive_after_action.py` 直接捕获 → **要继承**。

因为 world 的异常**真的跨过了 tool 层**（§4 会给出这条判断的实测依据），
它会被 `RunHarness.dispatch` 的 `except AgentError` 接住——"单局异常不崩掉整个 run"
这条 run 级契约靠的正是这个共同祖先。**它是四模块里唯一合法继承 `AgentError` 的。**

**所以出边归零要分两步走**：`tools.prompts` 那条**直接改**（§7 档 1a）；
`AgentError` 那条**要先动 P4 的桥**（§7 档 2b），否则改了就是拆承重墙。

### 1.3 这条环有多真（模块图上的证据）

```
world/pyboy_world.py:26  ──► pokemon_agent.tools.prompts
                                └──► tools/prompts/__init__.py:141
                                       └──► tools/prompts/decide_action.py:30
                                              └──► pokemon_agent.world   ← 回到起点
```

**这是一条货真价实的环**（world.pyboy_world → tools.prompts → world）。
它现在**不炸**，纯粹是因为 `world/__init__.py` 的 `interface/` 是 eager、而
`pyboy_world` 是 lazy——**`world` 包在 `pyboy_world` 加载之前已经初始化完毕**，
于是 `decide_action.py:30` 那行拿到的是成品。

**这层保护是脆的**：只要有人把 `pyboy_world` 挪进 `__init__` 的 eager 段
（P7 说"数据形状立即加载、实现懒加载"——但这条规则的边界随时可能被后人放宽），
或者让 `world/interface/__init__.py` 也改懒加载，环立刻显形。
**P1 的判据不需要等它炸**——拷走 world，这条环就是 `ModuleNotFoundError`。

---

## 二、量化代价：出边把多少东西拖进了 world

`sys.modules` 增量实测（子进程隔离，`sys.path[0]=cwd`）：

| 入口 | `pokemon_agent.*` 总数 | 其中 **非 world** | 明细 |
|---|---|---|---|
| `import pokemon_agent.world` | 17 | **0** ✅ | 16 个 `world.*` + 包自身 |
| `import pokemon_agent.world.errors` | 19 | **2** | `pokemon_agent` + `pokemon_agent.errors` |
| `import pokemon_agent.world.pyboy_world` | **102** | **82** ❌ | brain 17 / schemas 54 / tools 4 / harness 4 / config 1 / errors 1 |
| （对照）`import pokemon_agent.build` | 188 | — | brain 19 / harness 54 / schemas 59 / tools 16 / trace 8 / **world 20** / memory 8 |

**读法**：

- **第 1 行是 P7 做对了的证据**：`world/interface/` eager + 实现 lazy，
  所以"只想拿一个 `Observation` 的调用方"不吃 PyBoy。
- **第 3 行是出边的代价**：world 的核心实现一被加载，**82 个兄弟模块跟着进来**，
  其中 54 个是 `schemas.*`（`schemas/harness/__init__.py` 是 eager 全量聚合包的
  老问题，见 memory 审计 §0）。**"world 拷走"这件事在物理上不可能**。

### 阻断式实验（最硬的证据）

用 `importlib.abc.MetaPathFinder.find_spec` 阻断（**不用** `find_module`，
见 memory 审计 §8 第三个坑），逐条实测：

```
阻断 pokemon_agent.tools    → import pokemon_agent.world              OK（eager 面干净）
阻断 pokemon_agent.tools    → import pokemon_agent.world.pyboy_world  ✗ 需要 tools
     调用链：pokemon_agent/world/pyboy_world.py:26                              ← 直接违规点
阻断 pokemon_agent.errors   → import pokemon_agent.world              OK
阻断 pokemon_agent.errors   → import pokemon_agent.world.errors       ✗ 需要 errors
     调用链：pokemon_agent/world/errors.py:24                                  ← P3 例外点
阻断 pokemon_agent.errors   → import pokemon_agent.world.pyboy_world  ✗ 需要 errors
     调用链：pyboy_world.py:29 → world/errors.py:24
阻断 pokemon_agent.schemas  → import pokemon_agent.world.pyboy_world  ✗ 需要 schemas
     调用链：pyboy_world.py:26 → tools/prompts/__init__.py:141
                                 → tools/prompts/decide_action.py:30           ← 传递，非 world 的账
阻断 pokemon_agent.brain    → import pokemon_agent.world.pyboy_world  ✗ 需要 brain
     调用链：pyboy_world.py:26 → tools/prompts/__init__.py:141
                                 → tools/prompts/decide_action.py:28           ← 传递，非 world 的账
阻断 pokemon_agent.harness  → import pokemon_agent.world.pyboy_world  ✗ 需要 harness
     调用链：… → decide_action.py:30 → schemas/harness/__init__.py:156
                                 → …FromHarnessToReviewerReviewResp.py:7       ← 传递，非 world 的账
```

**归因（P4 的教训"首触模块 ≠ 责任模块"，但这次反过来用）**：
后三条的**首触帧全部是 `pyboy_world.py:26`**——那个**唯一需要修的**帧。
**只要把 `pyboy_world.py:26` 那一行拿掉，后面三条一起消失。**
换句话说：**world 84 个非自身模块的传递拉起，根子是那一行 import。**

---

## 三、P2 依赖三分类：入边 22 条逐条清点

### 全文清单（`grep -rn "from pokemon_agent.world" pokemon_agent/`，去掉 world 包内自指）

| # | 位置 | 拿什么 | 类别 | 判定 |
|---|---|---|---|---|
| 1 | `build.py:30` | `PyBoyWorld` | **第一类 实现依赖** | ❌ **越界**（`build.py:89` 真 `new`） |
| 2 | `harness/episode/episode_state.py:33` | `ActionSpace, Observation` | 第三类 形状 | ⚠️ 待定（见 §7 档 3） |
| 3 | `harness/episode/press/detect_stall.py:21` | `Observation` | 第三类 | ⚠️ 待定 |
| 4 | `harness/episode/press/perceive_after_action.py:51` | `BUTTON_FACING, Observation` | 第三类 | ⚠️ 待定 |
| 5 | `harness/episode/press/perceive_after_action.py:52` | `world.errors.{PerceptionAttemptFailed, PerceptionFailure}` | **异常引用** | ⚠️ 待定（与 P3/P4 绑定） |
| 6 | `harness/episode/retrieve/retrieve_global_episode_memory.py:23` | `Observation` | 第三类 | ⚠️ 待定 |
| 7 | `harness/episode/retrieve/retrieve_knowledge_semantic_memory.py:21` | `Observation` | 第三类 | ⚠️ 待定 |
| 8 | `harness/episode/store/store_object_semantic_memory/rules.py:59` | `BUTTON_FACING, FACING_STEP, INTERACT_KEY, Observation, PlaceInWorld` | 第三类 **＋ 真构造** | ⚠️ 待定（**唯一在 harness 里 `new` world 形状的地方**） |
| 9–16 | `schemas/harness/communication/` 8 封信封 | `Observation`×6 / `ActionSpace`×2 / `PlaceInWorld`×1 | 第三类 | ⚠️ 待定 |
| 17 | `tools/brain_tool.py:73` | `DIRECTION_KEYS, INTERACT_KEY` | 第三类 | ✅ **允许**（tool 层） |
| 18 | `tools/game_tools.py:29` | `OVERLAY_ACTIONS, ActionSpace, Facts, Observation, WorldPort` | 第三类 + 协议 | ✅ **允许**（且 `WorldPort` 是它注入的契约） |
| 19 | `tools/prompts/decide_action.py:32,33` | `terrain_legend, Facts` | 第三类 | ✅ **允许** |
| 20 | `tools/trace/render.py:43` | `Observation` | 第三类 | ✅ **允许** |
| 21 | `tools/vision_factory.py:29` | `VisionProvider` | 协议 | ✅ **允许**（接线工厂） |

**计数**：入边 **22** 条 = `build.py` 1 + `harness/` 7 + `schemas/harness/` 8 + `tools/` 6。
**非 tool 入边 = 16 条**（22 − 6）。

### 第一类（实现依赖）—— 只剩 1 处，与 memory/trace 对齐后唯一没做工厂的

```
build.py:30    from pokemon_agent.world import PyBoyWorld
build.py:86        vision = build_vision_provider(model=vision_model, temperature=0.0)
build.py:89        world = PyBoyWorld(rom, vision, state_path=state_file, watch=watch)
```

**四模块的收口进度（0913 当前）**：

| 模块 | 实现类 `new` 在哪 | `build.py` 的 import | 状态 |
|---|---|---|---|
| brain | `tools/brain_tool.py`（Brain + 四 provider） | 0 | ✅ 已收口 |
| memory | `tools/memory_tool.py`（Store×4 + FastEmbed×2） | 0 | ✅ 已收口（0913（60）） |
| trace | `tools/trace/`（`TraceTool.build()`） | 0 | ✅ 已收口（0913（61）） |
| **world** | **`build.py:89`（`PyBoyWorld()` 直接 `new`）** | **1** | ❌ **唯一没做工厂的** |

**而且最讽刺的一点**：world 的**感知 provider 工厂已经有了**（`tools/vision_factory.py`
的 `build_vision_provider()`，0913 深夜九为"world 的感知要一个 Qwen 实现"专门建的），
**结果 world 本体（`PyBoyWorld`）还是从 `build.py` 直接 `new`**——
"半个工厂"：**造零件在 tool 层，装配在装配点**。

### 第三类（形状引用）—— 15 条，但有一条是"真构造"

按 P2 原文，第三类「可接受，登记即可」；`AGENTS.md` 第十二节第 4 条就是登记表
（brain 那 33 处走的这条路）。**但 world 的第三类里混了一条不该混的**：

```
harness/episode/store/store_object_semantic_memory/rules.py:59
    from pokemon_agent.world import (BUTTON_FACING, FACING_STEP, INTERACT_KEY,
                                     Observation, PlaceInWorld)
    …… 而这一行是真的在 new：PlaceInWorld(...)（AST 调用点扫描实测）
```

**这条同时是三件事**：① 真构造 world 的形状；② 用了 world 的**世界语义常量**
（`BUTTON_FACING` / `FACING_STEP` / `INTERACT_KEY` = "这个世界怎么按键"的知识）；
③ 位置在 harness（该只做编排的地方）。**这不是"形状引用"，是 world 的世界知识
泄漏进了 harness**——它跟 `PlaceInWorld` 那 33 处 brain 形状引用不是一回事。

**这个模式本项目已经处理过一次**：`schemas/memory/datastore/object_memory.py`
曾经引用 `world.PlaceInWorld`，0913（13）的解法是**给 `ObjectFactEventBase` 做了
一个内部 `Place` 类**、把转换推给组装方。world 这条入边可以做同一件事。

---

## 四、P3 / P4：world 是"唯一该继承 `AgentError` 的模块"，代价是出边不为零

### 4.1 P3 的判据在 world 上成立了——但**方向反过来**

P3 的原判据：**「这条异常有没有跨过 tool 层这座桥」**。分两类：

| | brain | **world** |
|---|---|---|
| 异常在哪被接住 | `BrainTool._attempt_loop` | **`harness/.../perceive_after_action.py:88`** |
| 接住之后做什么 | 重试 → 耗尽翻译成 `MaxRetriesExceeded` | 重试 → 耗尽**抛 `PerceptionFailure`**（**还是 world 的类**） |
| 走到 harness 的 `except AgentError` 吗 | **不走** | **走** |
| 该继承 `AgentError` 吗 | 否（自成 `BrainError`） | **是**（0913 深夜十一定案） |

**所以 `errors.py:24` 那条出边，是 P3 判据主动要求保留的。** 它不是"还没清的债"，
它是"这条债的利息正被人用着"。

### 4.2 但 P4 说：桥只建在 tool 层——**world 的重试循环建在 harness 里**

```
brain 的桥（✅ P4 合格）：
  brain 抛 AttemptFailed ──► tools/brain_tool.py `_attempt_loop` 捕获、重试
                          ──► 耗尽抛 MaxRetriesExceeded ──► harness 的 except AgentError

world 的桥（❌ 桥建在 harness 里）：
  world 抛 PerceptionAttemptFailed ──► harness/episode/press/perceive_after_action.py:88
                                       自己 `for attempt in range(PERCEPTION_MAX_RETRIES)`
                                    ──► 耗尽抛 PerceptionFailure（world 的类）
                                    ──► 一路飘到 harness 的 except AgentError
```

**两处不对称，一处越界**：

1. **重试循环的位置**：brain 在 tool 层，world 在 **harness 节点**里。
   `perceive_after_action.py` 的 docstring 自己写着
   "循环与端口调用在这里，`perceive_once()` 只负责单次尝试"——
   这条设计**当年是刻意的**（账要由宿主写），但它**同时是 world 必须继承
   `AgentError` 的直接原因**：不为别的，就因为这个循环不在桥上。
2. **翻译动作不存在**：brain 的异常被**翻译**成 tool 层的词汇
   （`MaxRetriesExceeded`）；world 的异常**没有任何翻译**，原样上抛。
   P4 的"翻译点唯一"在 world 这条链上**是零个翻译点**。
3. **`tools/interface/ports.py:179` 已经承诺了 world 的异常**
   （"失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`"）——

**这三条合起来给了一个明确结论**：
**world 要出边归零，必须把 `perceive_with_retry` 搬进 `GameTools`**
（对齐 `BrainTool._attempt_loop`）。搬完之后：
world 的异常在 tool 层就被吃掉、翻译成 `MaxRetriesExceeded` → **走不到 harness**
→ `world/errors.py` 可以自成一根 `WorldError(Exception)` → **出边归零**。
**这一步同时消掉入边 #5**（harness 不再需要 import `world.errors`）。**详见 §7 档 2b。**

---

## 五、P5 / P6：world 已经做对了（实测）

### P5（同形不同约）—— ✅ 已达标，`world` 侧是主角

`world.VisionProvider` 与 `brain.interface.JudgeProvider` 描述同一个物理能力
（会 `describe()` 的模型），分属两家。本轮实测：

```
issubclass(QwenProvider, world.VisionProvider) = True     ← 实现同时满足两个协议
issubclass(QwenProvider, brain.JudgeProvider)  = True
world.VisionProvider is brain.JudgeProvider    = False    ← 谁都没 import 对方
world.VisionProvider 的方法: ['__init__', 'describe']
brain.JudgeProvider  的方法: ['__init__', 'complete', 'describe']   ← 超集（鸭子类型桥）
```

**判定**：符合 P5。三点都对——两边各自声明、实现（`_MultimodalMixin`）同时满足、
装配点靠字段结构对上打通。

### P6（信封本地化）—— ✅ 已做过一次，但**只做了信封，没做素材**

`world/interface/domain/vision_describe.py` 是 world 复制的一份**两封信封**
（`VisionDescribeReq`/`VisionDescribeResp`）。逐字段同构实测：

```
VisionDescribeReq : world=pokemon_agent.world.interface.domain.vision_describe
                    逐字段同构 = True | 字段名集合相同
VisionDescribeResp: 逐字段同构 = True | 字段名集合相同
```

**判定**：符合 P6。**但 P6 的手法在 world 上还有一处没用到**——
`perceive_screen.md`（**素材**）没有本地化，还留在 `tools/prompts/calls/`。
P6 讲的是"**两边各持一份副本，漂移就是运行时错误**"，
**信封已经这么做了，素材却没有**——这是 §7 档 1a 的依据。

---

## 六、P7：world 做对了，而且**做得比 brain 还细**——但这掩盖了出边

### 现状：三层分级，比 brain 的"两层"更精细

```
world/__init__.py
  ├── from .interface import (…31 个名字…)         ← eager：零依赖纯协议 + pydantic
  ├── if TYPE_CHECKING: from .{frame_slot,pyboy_world,ram} import …
  └── _LAZY: __getattr__                            ← lazy：pyboy_world / ram / frame_slot
```

**`import pokemon_agent.world` 实测拉起 17 个模块，全是 world 自己**——
这是 §2 表格第 1 行。**drowsy 的代价控制是对的**：`pyboy` + `PIL` 被关在
懒加载的 `pyboy_world.py` 里，只想拿 `Observation` 的调用方不吃它们。
（`world/__init__.py` 的 docstring 也把这条理由写清了。）

### **但这个分层同时把出边盖住了**

`import pokemon_agent.world` 干净 ≠ world 干净。
`world/errors.py`（→ `pokemon_agent.errors`）和 `world/pyboy_world.py`
（→ `tools.prompts`）**都不在 eager 段里**，所以"单跑一句 `import pokemon_agent.world`
成功"这件事**不能证明出边为零**。

这正是 skill 坑清单第 5 条（**懒加载会掩盖链**）：
"别用'单独 import 成功'证明'不依赖'"。
**world 是这个坑最极端的一例**：单 import 成功，单 import 核心实现拖进 82 个模块。

---

## 七、如何移出：三档，按"能不能不动架构"排序

### 档 1：出边（P1）——**必改**

#### 1a. `perceive_screen.md` 本地化进 world ✂️ 必做、低风险

**动作**：新建 `world/prompts/`（或 `world/interface/prompts/`），把
`tools/prompts/calls/perceive_screen.md` 挪进去；world 自持一份 20 行的读取器
（`PromptTemplate` + `load()`，`string.Template` 语义照抄）。

**依据**（三份，互相独立）：

1. **P1 判据**：拷走 `world/` 后感知还跑得起来吗 → 现在是**跑不起来**。
2. **消费者归属**：`tools/prompts/__init__.py` 的 docstring 自己说
   "`PyBoyWorld` 自己 `load()` 并渲染，是**拥有这次 LLM 调用的那个类**自己的事"。
3. **P6 手法已经在本模块用过一次**（`vision_describe.py` 的信封副本），
   素材本地化是同一招的下一次适用。

**占位符面很小**——`perceive_screen.md` 只有两个占位符：

```
$known_map            ← pyboy_world.py:353 传 terrain.render()
$terrain_legend       ← pyboy_world.py:353 传 terrain_legend()
```

**配套**（别漏，否则留下第二份真源）：

- `tools/prompts/__init__.py` 的 docstring「四份平铺在 `calls/` 下」要改成三份，
  并注明 `perceive_screen` 已归 `world/`；
- `load()` 的 `_find()` 递归不会命中 `world/` 之外的目录，**不存在重名风险**
  （它的 `assert len(matches) <= 1` 照旧成立）；
- `tools/prompts/` 里没有任何 `.py` 引用 `perceive_screen`（本轮已查，只有一个
  docstring 提它）。

**改完的验收判据**：

```bash
grep -rn "pokemon_agent.tools" pokemon_agent/world/     # 必须无输出
python -c "import pokemon_agent.world.pyboy_world"      # 非 world 模块数 82 → 0
```

#### 1b. `AgentError` ——**不能单独改**，与档 2b 绑定

见 §4 与档 2b。**单删继承 = 拆掉"单局异常不崩掉整个 run"的承重墙。**

---

### 档 2：入边（P2 一/三类）——**必改 + 建议改**

#### 2a. `GameTools.build()` 收口（对齐其余三模块）✂️ 必做

**为什么必须做**：这是"外部只有 tool 对 world 有**实现依赖**"这句命题唯一的例外，
且其余三模块都已收口（§3 表格）。**没做的理由一个都没有**。
而且 world 的**零件工厂已经有了**（`vision_factory.build_vision_provider`），
只差把"造 `PyBoyWorld` + 挂感知 provider"这一步从装配点搬进 tool 层。

**最小改法**（建议与 `BrainTool.build` / `MemoryTool.build` / `TraceTool.build` 同形）：

```python
# tools/game_tools.py —— 新增类方法
@classmethod
def build(
    cls,
    rom: str,
    *,
    state_path: str | None = None,
    watch: bool = False,
    vision_model: str = "qwen3.8-max",
) -> GameTools:
    """造一个接了真实世界的 GameTools——装配点唯一的入口。

    **为什么"造 PyBoyWorld + 挂哪个感知实现"收在这一处**：与
    `BrainTool.build()` / `MemoryTool.build()` / `TraceTool.build()` 同一条判据——
    "这个技能接哪个实现"是这条链路的接线知识，装配点不该 import 具体类。
    """
    # 导入放函数内：`pyboy_world` 拖着 pyboy + PIL，不该在 import 本模块时连带拉起。
    from pokemon_agent.world import PyBoyWorld

    return cls(PyBoyWorld(rom, build_vision_provider(model=vision_model,
                                                     temperature=0.0),
                          state_path=state_path, watch=watch))
```

```python
# build.py —— 删 L30 的 import、把 L86+L89 合成一行
game = GameTools.build(rom, state_path=state_file, watch=watch, vision_model=vision_model)
```

**两个要一起处理的细节**（不处理会留下新债）：

1. **`build_real` 的返回类型**：现在是 `tuple[RunHarness, PyBoyWorld, GameTools]`，
   那个 `PyBoyWorld` 名字就是 `build.py` 第 30 行的由来。两条路：
   - **(i) 还 world 本体、注解** `TYPE_CHECKING`：`if TYPE_CHECKING: from pokemon_agent.world import PyBoyWorld`。
     **运行期 import 面 = 0，AST import 面 = 1（TYPE_CHECKING）**——
     与 memory/trace 的"AST import 点 = 0"**不完全同级**。
   - **(ii) 让 `GameTools` 接管生命周期**（`close()` / `latest_frame()` 已经在它身上了），
     `build_real` 返回 `tuple[RunHarness, GameTools]`。**实测支持这么做**：
     `api.py:326` 那句 `return harness, world, tools.latest_frame`，
     `world` 被塞进 `_RunHandle.world` 并注解为 **`Any`**，
     而全项目**没有任何一处调用 `.close()`**（只有注释说"run 结束后关闭"）。
     **推荐 (ii)**——顺手把一条死边（返回值里的 world）清掉，与 trace 那次
     "`build_real` 返回值从 4 元组收成 3 元组（`trace` 那项零消费者）"**同款**。

2. **`api.py` 的 `handle.world`**：若走 (ii)，这个字段要么删（同 trace 删
   `_RunHandle.trace` 的理由），要么改成 `handle.game_tools`。

**验收判据**：

```bash
grep -n "pokemon_agent.world" pokemon_agent/build.py   # 必须无输出
# build.py 顶层拖进 world 子模块数：20 → 0（K 参数下 api.py 仍需真实 world 生命周期）
```

#### 2b. 把 `perceive_with_retry` 搬进 `GameTools`（对齐 `BrainTool._attempt_loop`）⚠️ **需拍板**

**这一步同时拿下三件事**（这是全篇最集中的一处收益）：

| 拿下什么 | 怎么拿下的 |
|---|---|
| world **出边最后一条**（`errors.py:24` → `AgentError`） | 异常在 tool 层就被翻译，走不到 harness ⇒ world 自成 `WorldError(Exception)` |
| 入边 **#5**（`perceive_after_action.py:52` → `world.errors`） | harness 不再需要认识 world 的异常 |
| P4 **桥的位置**（world 的重试循环从 harness 回到 tool 层） | 与 brain 对齐，"桥只建在 tool 层"从 3/4 变 4/4 |

**形状（照 `BrainTool._attempt_loop` 抄）**：

```python
# tools/game_tools.py —— 循环与翻译都在这里（对应 brain 的 _attempt_loop）
def perceive_with_retry(self, *, ram_only: bool = False) -> FromHarnessToGameToolPerceiveOnceResp:
    log: list[tuple[int, ModelCall]] = []
    for attempt in range(1, PERCEPTION_MAX_RETRIES + 1):
        try:
            return self._world.perceive_once(ram_only=ram_only)
        except PerceptionAttemptFailed as exc:          # ← world 的词汇，桥上认识，桥外不认识
            log.append((attempt, ModelCall(payload=exc.call,
                                           error_kind="PerceptionParseFailure",
                                           error=exc.call.get("raw", ""))))
    raise MaxRetriesExceeded(len(log), last_reason, calls=[c for _, c in log],
                             source="perception")        # ← tool 层的升级态（已存在，无需新类）
```

```python
# harness/episode/press/perceive_after_action.py —— 节点只剩"写账 + 上抛"
try:
    resp = deps.game.perceive_with_retry(ram_only=ram_only)
except MaxRetriesExceeded as exc:
    deps.trace.append_model_calls(FromHarnessToTraceToolAppendModelCallsReq(
        episode_id=episode_id, step=step, source=Source.PERCEPTION,
        log=[(i + 1, c) for i, c in enumerate(exc.calls)]))   # 账照样落在宿主里
    raise
```

```python
# world/errors.py —— 自成一根根（照 brain 的 BrainError）
class WorldError(Exception):
    """world 的内部失败根。**不继承 `AgentError`**——world 的异常在
    `GameTools.perceive_with_retry` 里就被翻译成 `MaxRetriesExceeded`，
    走不到 `RunHarness.dispatch` 的捕获点（判据同 brain）。"""

class PerceptionAttemptFailed(WorldError): ...
```

**连带要改的文档**（否则留下两处互相矛盾的真源）：
`pokemon_agent/errors.py` 的模块 docstring 有一整段在讲"world 的异常为什么继承
`AgentError`"，`world/errors.py` 的 docstring 同款——两处都要改成"now translated
in tool layer"。

**取舍（诚实说）**：

- *为什么值得*：这是让 world 出边**真正归零**的唯一路径，且顺手把 P4 补成 4/4。
- *代价*：动了 `perceive_after_action.py` 一条**当年刻意的**设计决策
  （docstring 明写"循环与端口调用在这里……账要由宿主写"）；
  账的写入点从"重试循环内部逐次"变成"异常携带整条账、宿主一次写"——
  与 `MaxRetriesExceeded.calls` 的既有语义一致，但要核对
  `FromHarnessToTraceToolAppendModelCallsReq` 的 `attempt` 编号口径
  （现在是循环里传 `attempt`，改后按 `enumerate` 派生）。
- *如果你更看重"别动已跑通的重试路径"*：**档 1b 就不做**，
  世界出边停在 **1 条**（`AgentError`），并在 `AGENTS.md` 登记为
  **P3 判据主动保留的例外**——这也是一个自洽的终态（world 与 brain 的差别
  由此变成"有没有跨过 tool 层"的可核对事实，正是 P3 想要的）。

---

### 档 3：入边形状归零 —— ⚠️ **大改，需明确拍板**

**先说清标准问题**：P2 原文写的是第三类「可接受，登记即可」，brain 有 **33 处**
就是这么登记的。**但 trace 那一轮用户把标准收紧了**：

> 目标已收紧：从"harness 只剩 4 处形状引用、登记即可"改成
> **"非 tool 引用一律为 0"** —— 全仓库只允许 `tools/` import `pokemon_agent.trace`。

**用户这次的原话（"外部只有 tool 对其依赖"）读起来是同一个收紧口径。**
按这个口径，world 要清的是 **16 条非 tool 入边**（§3 的 #1–#16，其中 #1 归档 2a）。
形式化判据：

```bash
grep -rn "from pokemon_agent.world" pokemon_agent/ --include="*.py" \
  | grep -v "^pokemon_agent/tools/"      # 必须无输出
```

要清的名字（非 tool 侧，去重）：

| 名字 | 非 tool 引用处 | 性质 |
|---|---|---|
| `Observation` | schemas 4 封 + harness 4 处 | 形状 |
| `ActionSpace` | schemas 2 封 + harness 1 处 | 形状 |
| `PlaceInWorld` | schemas 1 封 + harness 1 处（**真构造**） | 形状 + 世界语义 |
| `Facts` | （被 `Observation` 引用，级联） | 形状 |
| `BUTTON_FACING` / `FACING_STEP` / `INTERACT_KEY` | harness `rules.py` / `perceive_after_action.py` | **世界语义常量** |
| `PerceptionAttemptFailed` / `PerceptionFailure` | harness 1 处 | 异常（归档 2b） |

#### 方案 W-A（双坐，P6 手法）—— 唯一能同时满足两半的路

```
schemas/world/domain/…      ← 项目侧副本（schemas + harness 用；权威给"项目记账"）
world/interface/domain/…    ← world 侧副本（world 的 ram.py / pyboy_world.py 真构造）
```

- tool 层（`game_tools.py`）加**转换函数**：world 形状 → 项目形状。
  这与它**已经在做的**事同款（`FromHarnessToGameToolPerceiveOnceResp` 的组装就在那里）。
- 两份**逐字段同构**，靠 P6 的兜底（docstring 明写"必须保持同构" + **改动时人工核对**）。
- **本项目已有先例**：`schemas/memory/datastore/object_memory.py` 的
  `ObjectFactEventBase.Place` 就是为脱开 `world.PlaceInWorld` 而做的内部类
  （0913（13））。

**代价（必须诚实列出）**：
- **级联**：`Observation` 引 `Facts` / `PlaceInWorld`；`Facts` 引 `ScreenState`……
  一搬就是 `domain/` 整个搬迁，**不是"挪几个类"**；
- world 的 `__init__.py`（31 个名字的 eager 出口）要跟着拆成两套出口；
- 从此**每个新字段都要改两处**，且漂移只在运行时炸（P6 的固有代价）。

#### 方案 W-B（把形状搬去 schemas、world 反向 import）—— ❌ **直接违反 P1**

world 出边从 2 条变成整个 `schemas.*` 子包。**不提。**

#### 方案 W-C（Protocol，trace 用过的那招）—— ❌ **在 world 上不成立**

**这是 world 与 trace 的根本差别，值得单列**：

| | trace | **world** |
|---|---|---|
| 模块对形状的需要 | 只读 6 个**属性名**（`event_id`/`step`/`type`/…） | **真的 `new` 出具体类**（`ram.py:210/211/266` 造 `TerrainMap`、`pyboy_world.py:383` 造 `perceive_screen` 结果、`rules.py` 造 `PlaceInWorld`） |
| Protocol 够不够 | **够**（`@runtime_checkable` + 结构化满足，0913（61）已落地） | **不够**（要 `model_validate` / 构造 / 字段默认值，纯协议给不了） |
| 结论 | 协议方案**作废了双坐副本** | **双坐是唯一路**（W-A） |

---

## 八、改动清单（按依赖顺序）

| # | 档 | 文件 | 改动 | 前置 |
|---|---|---|---|---|
| 1 | 1a | `world/prompts/perceive_screen.md` | 从 `tools/prompts/calls/` **搬入** | — |
| 2 | 1a | `world/prompts/__init__.py`（新） | 自持 `PromptTemplate` + `load()`（照抄 20 行） | 1 |
| 3 | 1a | `world/pyboy_world.py:26,192` | import 与 `load_prompt` 改指 `world.prompts` | 2 |
| 4 | 1a | `tools/prompts/__init__.py` | docstring「四份」→「三份」+ 注明 `perceive_screen` 已归 world | 1 |
| 5 | 2a | `tools/game_tools.py` | 新增 `build()` 类方法（内部 new `PyBoyWorld`） | — |
| 6 | 2a | `build.py:30,86,89` | 删 import；两行合成 `GameTools.build(...)` | 5 |
| 7 | 2a | `build.py:61` + `api.py:326,173` | 返回值收成 2 元组（world 项零消费者，同 trace 那次） | 6 |
| 8 | 2b | `tools/game_tools.py` | 新增 `perceive_with_retry()`（循环 + 翻译成 `MaxRetriesExceeded`） | 5 |
| 9 | 2b | `harness/episode/press/perceive_after_action.py:88-142` | 循环摘除；`except MaxRetriesExceeded` 写账后上抛 | 8 |
| 10 | 2b | `world/errors.py:24,27,44` | 删 `AgentError`，新增 `WorldError(Exception)` | 9 |
| 11 | 2b | `pokemon_agent/errors.py`（docstring） | 「world 保留继承」段改成「由 tool 层翻译」 | 9 |
| 12 | 3 | `schemas/world/domain/**`（新） | 项目侧副本，与 `world/interface/domain/` 逐字段同构 | 拍板 |
| 13 | 3 | `schemas/harness/communication/*` 8 封 | import 改指 `schemas.world` | 12 |
| 14 | 3 | `harness/**` 6 个文件 | 形状 import 改指 `schemas.world`；`rules.py` 的 `PlaceInWorld` 构造改经转换 | 12 |
| 15 | 3 | `tools/game_tools.py` | 加 world 形状 → 项目形状的转换 | 12 |

**第 1–4 项（档 1a）零风险、可立刻做**；**5–7 项（档 2a）是"把已在别处做过的事补上"**；
**8–11 项（档 2b）与 12–15 项（档 3）需要拍板。**

---

## 九、可复现的核对方法

```bash
PY="C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe"

# ① 出边 AST 审计（world/ 对 pokemon_agent.* 的外部依赖，应为 0）
python <skill>/python-import-dependency-audit/scripts/import_audit.py direct pokemon_agent world

# ② 入边清点（全项目对 world 的 import，按消费者域分类）
grep -rn "from pokemon_agent.world" pokemon_agent/ --include="*.py" | grep -v "__pycache__"

# ③ 真·构造点（AST 扫 ast.Call，不扫 import）——本轮用的脚本见下
python - <<'EOF'   # 引用名出现在 ast.Call.func 才是"实现/构造"，只在注解里不算
# 见 §3 表格第 8 行：rules.py 的 PlaceInWorld(...) 就是靠这一步抓出来的
EOF

# ④ sys.modules 增量（量化出边代价）
python -c "import sys;b=set(sys.modules);import pokemon_agent.world.pyboy_world;\
print(len([m for m in set(sys.modules)-b if m.startswith('pokemon_agent')]))"   # → 102

# ⑤ 阻断实验（模拟"world 被拷走/被阻断"）
python <skill>/.../import_audit.py block pokemon_agent.world pokemon_agent.build,pokemon_agent.harness

# ⑥ P5 / P6 协议桥与副本同构核对
#    issubclass(QwenProvider, {world.VisionProvider, brain.JudgeProvider})
#    vision_describe 两封信封的 model_fields 逐字段比对
```

### 本轮踩到的坑（承接 memory 审计 §8）

| 坑 | 表现 | 对策 |
|---|---|---|
| **懒加载掩盖出边**（skill 坑 5） | `import pokemon_agent.world` 成功、且拉起 17 个模块全是 world 自己——**看起来出边为零** | 出边必须**逐个懒加载子模块各跑一次**，或直接 AST 全树扫（本节 ①） |
| **首触帧 ≠ 责任帧**（skill 坑 4） | 阻断 `schemas`/`brain`/`harness` 都会让 `pyboy_world` 炸，**看起来 world 依赖三家** | 追栈到**最长那条项目内帧**，发现三条链的**共同首帧都是 `pyboy_world.py:26`**——一处修、三条消 |
| 阻断哨兵不能是 `ImportError` 子类（skill 坑 9） | 用 `except ImportError` 会把"包找不到"一起吞 | 自定义 `class _Blocked(Exception)`；脚本入口 `sys.path.insert(0, os.getcwd())` |
| 环境 | managed 3.13 缺依赖；仓库 `.venv` 是 linux 版 | **用 Python312**（同 memory 审计） |

---

## 十、验收（现状基线，供改完对照）

- **出边**：AST 全树 `world/` 对 `pokemon_agent.*` 外部依赖 = **2**
  （`errors.py:24`、`pyboy_world.py:26`）。
- **出边代价**：`import pokemon_agent.world.pyboy_world` 拉起非 world 模块 **82** 个
  （brain 17 / schemas 54 / tools 4 / harness 4 / config 1 / errors 1）。
- **`import pokemon_agent.world`（eager 面）**：17 个模块，**非 world = 0** ✅。
- **入边**：**22** 处 = `build.py` 1 + `harness/` 7 + `schemas/harness/` 8 + `tools/` 6；
  **非 tool = 16**。
- **实现依赖落点**：`build.py:30`(import) + `build.py:89`(`new`) = **1 处**，
  是四模块里**唯一**没做工厂的。
- **逐文件核对**：19 个 py 文件，出边只出现在 2 个文件里；`interface/` 10 个文件**零出边**。
- **P5**：`QwenProvider` 对两个协议 `issubclass` 均为真；两协议 `is not` 同一对象。
- **P6**：`vision_describe` 两封信封逐字段同构 = True；**素材未本地化**（`perceive_screen.md`）。
- **P7**：`interface/` eager（16 个子模块）+ 实现 lazy 分级正确；
  **但该分级让出边不可见**。
- **未跑真实 harness**（按规矩由用户运行）；未发真实 API 请求。
- **本轮未改任何代码**——纯审计。

---

## 十一、待用户拍板的三件事

1. **档 2b 做不做**（把 `perceive_with_retry` 从 harness 搬进 `GameTools`）——
   这决定 world 出边停在 **1 条**（保留 `AgentError`，登记为 P3 例外）
   还是 **0 条**。**做** → 出边归零 + P4 补成 4/4，代价是动一条已跑通的重试路径；
   **不做** → 停 1 条，自洽且零风险。
2. **入边标准**：第三类形状引用按 P2 原文「登记即可」（brain 33 处的先例），
   还是按 trace 那次收紧的「非 tool 一律为 0」？
   后者意味着**档 3 的 16 条**要清，路径只有 **W-A 双坐**（`domain/` 整个搬迁 + 两套出口）。
3. **档 2a 的返回类型**：`build_real` 走 (i) `TYPE_CHECKING` 注解
   （AST 面 1）还是 (ii) 让 `GameTools` 接管生命周期、返回值收成 2 元组
   （AST 面 0，且顺手清掉一条死边，与 trace 那次同款）？
