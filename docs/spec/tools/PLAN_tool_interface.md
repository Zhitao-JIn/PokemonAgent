# PLAN：给 tool 层补上抽象接口（`tools/interface/`）

> 状态：**v2，方案稿，等两条确认**。按既定做法，**拍板前不动代码**。
>
> **v1 → v2 改了什么、为什么**（2026-09-12）：
> - v1 §3 摆了四张"策略表"让你挑一条——**读错了**。你说的是"策略模式指的就是依赖注入这类，
>   harness 依赖 toolport，tool 只需要实现 port"，也就是 **v1 §2 本身**。§3 因此从"选择题"
>   降级成一小段**已排除记录**（那四张表都不是本次目标，理由留档省得重开）。
> - v1 §4 问"`schemas/` 改不改名"——**已拍板：不改名**。§4 改成记录这条决定 + 它连带澄清的
>   一件事（那次改名计划的前提确实已经不成立）。
> - 新增 §6：唯一还需要你点的是**"interface"指哪个 interface**——仓库里"接口"这个词
>   有两个互相矛盾的出处（`AGENTS.md` §四 与 `docs/spec/interfaces/SPEC.md` 都指向一个
>   **今天不存在的顶层 `interfaces/`**），这很可能正是你说"放到 interface 里"时的所指。

---

## 1. 改造前的现状：可测的证据（v2 时点；**已改造，结果见 §7**）

### 1.1 `tools/` 的协议和它的实现住在同一个出口里

`tools/` 是六个领域层里**唯一**一个"统一出口把抽象和实现一起导出来"的层：

```python
# pokemon_agent/tools/__init__.py（现状）
__all__ = ["BrainTool", "BrainToolPort", "CheckpointTool", "CheckpointToolPort",
           "GameTools", "GameToolPort", "MemoryTool", "MemoryToolPort",
           "TraceTool", "TraceToolPort"]
from .brain_tool import BrainTool            # ← 插件
from .checkpoint_tool import CheckpointTool  # ← 插件
from .game_tools import GameTools            # ← 插件
from .memory_tool import MemoryTool          # ← 插件
from .trace_tool import TraceTool            # ← 插件
from .ports import BrainToolPort, ...        # ← 协议
```

后果是**可测量的**：只要从 `pokemon_agent.tools` 拿一个名字，Python 就必须先把
`__init__.py` 跑完，于是五个插件全部落到 `sys.modules`。

| 实测（本机 3.12，`sys.modules` 增量） | 加载的 `pokemon_agent` 模块数 | 有没有 `tools.*` 插件 |
|---|---|---|
| `from pokemon_agent.schemas.harness import FromHarnessToGameToolExecuteReq` | **113** | 无 ✓ |
| `from pokemon_agent.tools import GameToolPort`（只想要一张协议） | **146** | **`tools.brain_tool`/`checkpoint_tool`/`game_tools`/`memory_tool`/`trace_render`/`trace_tool` 全部 ⚠** |
| 同上，另外被连带拖进来的 | — | `trace.store`（`LocalTrace`）、`memory` 包（`store`/`retrieval`）、`prompts.decide_action`、`harness.interface`、`brain.interface`、`world.*` 全包 |

对照实验：`memory/` 也走扁平的 `ports.py`，但 **`from pokemon_agent.memory import MemoryStorePort`
只付 5 个模块**——它的问题是文件布局，`tools/` 的问题是**出口**。

### 1.2 "不认识具体插件"有两种读法，今天只兑现了第一种

| 读法 | 判据 | 今天 |
|---|---|---|
| **类型上不认识** | harness 的类型注解 / `isinstance` 只出现 Protocol，不出现具体类 | ✅ **已做到**（`grep` 干净） |
| **进程上不认识** | 拿到协议的那一刻，插件的模块**没有**被加载 | ❌ **没做到**（146 vs 113） |

铁律 2/3 与 `AGENTS.md`「接口先行」要的是同一件事：**换 mock 还是真实实现，调用方不该知道**。
今天 harness 从 `pokemon_agent.tools` 拿协议的有 **6 个文件**：

| 文件 | 拿了什么 |
|---|---|
| `harness/brain_utils.py:28` | `BrainToolPort` |
| `harness/episode_harness.py:113` | `BrainToolPort`/`CheckpointToolPort`/`GameToolPort`/`MemoryToolPort`/`TraceToolPort`（一次全拿） |
| `harness/game_utils.py:19` | `GameToolPort` |
| `harness/run_harness.py:62` | `BrainToolPort`, `CheckpointToolPort`, `TraceToolPort` |
| `harness/run_plan_utils.py:29` | `BrainToolPort` |
| `harness/trace_write.py:20` | `TraceToolPort` |

类型层面它们只认协议，但**进程层面五个插件已经全部加载**——"依赖注入管调用方根本不知道
自己拿的是谁"这句在 import 这一层没兑现：它确实不知道，但代价是"必须把五个人全请来，
才知道自己拿的是谁"。做 A2A / 拆包（ROADMAP 25）时，这一环会直接变成"拆不动"。

### 1.3 `tools/ports.py` 那段"不需要 `interface/`"的理由，今天要分条重读

`ports.py` 的 docstring 给了四条理由，逐条核：

| 原文 | 今天还成立吗 |
|---|---|
| 「五个 Port 全部只依赖 `schemas.harness` 的信封类型」 | ✅ 成立。**这正是搬进 `interface/` 的安全保证**：信封侧实测 113 模块、零 `tools.*`，不会绕出环 |
| 「没有自己专属的 domain schema（跟 world/trace/providers/brain 不同）」 | ✅ 成立（今天） |
| 「**所以**走扁平的 `ports.py`，跟实现文件同住 `tools/` 包顶层」 | ⚠️ **这一步不成立**：扁平讲的是"协议文件与实现文件平级"，而问题从来不是文件放在哪一级，是**`__init__` 把两者一起导出**。文件挪进 `interface/` 是在修这句话的后半截 |
| 「零循环依赖风险…不需要懒加载」 | ✅ 成立，搬完也**不需要**在 `interface/__init__.py` 里做 `__getattr__` 兜（对照 `harness/interface/__init__.py` 为什么必须做：那里 `schemas.harness` 会回头要 `HumanDecision`，`tools/interface` 没有这个回环） |

---

## 2. 主方案：抽象与插件分家（这就是你说的"策略模式"）

**它不是什么新花样**——`world`/`trace`/`providers`/`brain`/`harness` 五层早就各有一张
Port + 一套实现 + 一个只导出必要名字的出口；`tools/` 是**唯一破了这个对称**的一层。
本方案就是把对称补回来：**消费方依赖 Protocol，实现方只负责实现 Protocol，装配点
（`build.py`）是唯一认识具体类的地方。**

### 2.1 目标结构

```
pokemon_agent/tools/
├── interface/               ← 新增。只放抽象，import 得到的东西里没有任何插件
│   ├── __init__.py          ← 统一出口：只 re-export 那五张 Protocol
│   └── ports.py             ← 由 tools/ports.py 整体挪来（内容零改动）
├── brain_tool.py            ← 插件本体，一行不改
├── checkpoint_tool.py
├── game_tools.py
├── memory_tool.py
├── trace_tool.py
└── __init__.py              ← 统一出口收窄：只 re-export 五个**实现**
```

消费方的写法从 `from pokemon_agent.tools import GameToolPort` 变成
`from pokemon_agent.tools.interface import GameToolPort`；`build.py` 一行不改
（它反正要认识具体类，从 `pokemon_agent.tools` 拿）。

### 2.2 三个决定

1. **不预建 `interface/domain/`。** 这五张 Port 的签名今天**完全**由信封类型
   （`schemas.harness`）和标量构成，没有任何一张属于自己的形状。沿用 world/trace
   当初的判据——*有专属形状才开子包*——等真出现"门面对内说话用的裸形状"再加。
   空目录是负担，不是先见之明。
2. **`tools/__init__.py` 不再导出协议**（这是本次真正的修复，见 §2.3）。
   过渡期想少改文件，也可以让 `tools/__init__.py` 用 `__getattr__` 懒加载那五个
   协议——但**不建议**：那只是把 146 藏起来，谁先 `import pokemon_agent.tools`
   一次，账照付（`harness/interface` 的懒加载是被循环 import 逼出来的，不是风格）。
3. **`tools/ports.py` 不原地留转发文件。** 全仓库替换 import 路径（与早先
   `schemas` 内部那次搬家的做法一致）；留一个 `.py` 只做 re-export
   会让"协议住哪"永远有两个答案。

### 2.3 为什么不只是"原地改个名 / 原地加个 `__all__` 过滤"

- 只改名：零收益，问题在出口不在文件名。
- 只删 `tools/__init__.py` 里的协议导出、不建 `interface/`：**协议就没有家了**——
  它会被迫跟实现继续平级，或者散到 `build.py`，那才是真的架构后退。
- 本方案**三层**都要动：**协议换房 + 出口分家 + 实现懒加载**。少任何一层，
  验收 ① 都过不去（§7.1 把三层的账分别量了）。

### 2.4 它和 `harness/interface/` 是两个方向，不能合并

| | `harness/interface/` | `tools/interface/`（本方案） |
|---|---|---|
| 谁调用谁 | `RunHarness` → `EpisodeHarness`（**上层调下层**） | `EpisodeHarness`/`RunHarness` → 工具门面（**上层调门面，门面再往下**） |
| 协议是给谁看的 | run 级图看 episode 级图 | 两个 harness 看五张门面 |
| 放进同一个包会怎样 | —— | 混成"harness 层的协议"，`RunHarness→EpisodeHarness` 和 `Harness→Tools` 两种依赖方向就分不清了 |

---

## 3. 已排除：那四张"把决定写死成表"的地方（都不是本次目标）

v1 把它们误当成"策略模式"的候选，你已澄清策略模式 = 依赖注入。**留档以免重开**：
它们**都已经在对的地方**，本次一个都不动。

| | 现状（文件:行） | 为什么不撤 |
|---|---|---|
| ① 按键掩码 masking | 表在 `world/interface/domain/facts.py`（`OVERLAY_ACTIONS`），应用在 `tools/game_tools.py` | 表按"世界的形状"归 world 是对的；`pyboy_world.py` 还有一条 assert 拿它核对"按键世界能不能执行"，抽走会让那条 assert 失去着落 |
| ② trace 渲染分派 | `tools/trace_tool.py` 的 `_RENDERERS`（`TraceKind` → 函数），实现在 `trace_render.py` | `PLAN_harness_decoupling.md` §5.2 明确判过"按 `kind` 分派"，这是 tool 层该干的活 |
| ③ 检索策略（工具的读方法） | `tools/memory_tool.py` + `memory/retrieval.py` | 它**确实是**一条待重做的"策略"，但那是 ROADMAP 24 的事（0908 已拍板、待实施），属于**那张**计划，不塞进本次 |
| ④ 执行/中止策略 | `FromHarnessToGameToolExecuteReq.settle`、`StepMemory.stop`/`StopReason`、`compute_stop` | 已经分在 harness（`harness/episode_utils.py`），分对了 |

---

## 4. `schemas/` 不改名（已拍板 2026-09-12）

你已定：**不改名**。记下它连带澄清的一件事，免得以后再被那份计划牵回来。

`docs/PLAN_bare_boundary_refactor.md` 第 7 步写着"`schemas/` 改名 `communication/`"，
前提是"schemas 层里只留信封"。**这个前提今天不成立，而且是 (13) 条自己推翻的**——
搬完之后 `schemas/` 里还住着 `schemas/memory/datastore/`（`StepMemory`/`EpisodeMemory`/
`ObjectFactEvent` 三个**实体**，不透明、不属于通信协议），它们是 (13) 特意留下的。
所以"改名 `communication/`"会把三个实体归进一个叫"通信"的目录，比现在的名字更错。

**决定：维持 `schemas/`。** 那第 7 步就永远是"未执行"，按惯例**只加就地标注、不改历史论证**
（本次未动那份文件，留作单独一件事）。

> **顺带一条我自己的怀疑，本次撤回**：v1 疑过 `FromHarnessToMemoryToolQueryRecentStepsReq`
> 该跟着 (22) 条改名。不撤它——名字里的 `RecentSteps` 描述的是**查询面**（确实按"条数"
> 取回），只是调用方拿到后再按链裁；这是"名字描述哪一面"的取舍，不是错，改它是净亏损。

---

## 5. 迁移顺序（**已执行** 2026-09-12；原计划"每步一个 commit"，本次一次做完）

| 步 | 内容 | 实际 |
|---|---|---|
| 1 | `git mv tools/ports.py tools/interface/ports.py` + 新建 `tools/interface/__init__.py`（只导出五张协议） | ✅ 另把 `ports.py` 那段"不需要 `interface/`"的 docstring **就地标注为过期**，没删论证 |
| 2 | `tools/__init__.py` 去掉五张协议的导出 | ✅ 并且**补上了原计划没有的"实现懒加载"**（§7.1 说明为什么这一步不能省） |
| 3 | 全仓库替换 import → `pokemon_agent.tools.interface`（§1.2 那 6 个文件 + `tools/` 自身），用 `scripts/check_imports.py` 兜 | ✅ 6 个 harness 文件；`tools/trace_tool.py` 另有一处子模块 import 要改，见 §7.2 |
| 4 | `docs/spec/tools/SPEC.md` §1/§4 重述总表出处；`ports.py` 那段理由改写 | ✅ 另加了文首**现状块**（那份 SPEC 的滞后远不止协议住址，见 §7.2） |
| 5 | 验收 + CHANGELOG | ✅ 见 §7.3 |

**验收（可执行）**

```bash
# 1. 协议的 import 不再拖插件：只付信封的钱（实测应从 146 降到 ≈113，且 tools.* 为空）
python -c "import sys; b=set(sys.modules); \
from pokemon_agent.tools.interface import GameToolPort; \
t=[m for m in set(sys.modules)-b if m.startswith('pokemon_agent.tools')]; \
print(len([m for m in set(sys.modules)-b if m.startswith('pokemon_agent')]), t)"   # 期望：≈113 []

# 2. 没有任何地方再从 tools/ 根拿协议
grep -rn "from pokemon_agent.tools import .*ToolPort" pokemon_agent --include="*.py" | grep -v __pycache__   # 期望 0 行

# 3. 插件仍然只在装配点 new（这条本来就干净，别改坏）
grep -rn -E "(GameTools|MemoryTool|TraceTool|BrainTool|CheckpointTool)\(" pokemon_agent --include="*.py" | grep -v __pycache__   # 只允许 build.py 与 tools/ 自身

# 4. 抽象不碰插件（反向）
grep -rn "from pokemon_agent.tools import" pokemon_agent/tools/interface --include="*.py"   # 期望 0 行
```

**不做的事**（留个记号，免得以后当成漏做）：本次不碰 `memory/ports.py`（它没这个毛病，
实测 5 个模块）；不碰五个门面的方法签名；不新增 domain schema；不碰 `schemas/`。

---

## 6. 收口（原"还需要你确认的三条"）

1. **"放到 interface 里"指哪个 `interface`？—— 已拍板：A，`pokemon_agent/tools/interface/`**
   （2026-09-12，你的原话"就是自己模块下的interface"）。理由归档：现役五层
   （`world`/`trace`/`providers`/`brain`/`harness`）**都**是这么放的，`tools/` 补的是对称。
   选项 B（复活顶层 `pokemon_agent/interfaces/`）排除。§1.2 里那句"那些 Port 现在住在
   `tools/ports.py`"按本 PLAN 已经过期，读作 `tools/interface/ports.py`。

2. **§2.2 的三个决定** —— 不预建 `domain/`、出口收窄、不留转发文件：**三条都照做了**，
   其中决定 2 在执行中**补了原计划没有的"实现懒加载"**（§7.1 说明为什么它不能省）。

3. **顺手订正那两份过期文档吗？—— 仍待你点头，未动。** 两份都指向一个**不存在的**
   顶层 `interfaces/`：`AGENTS.md` §四 的目录树（"WorldPort / GameToolPort /
   MemoryToolPort …"）与 `docs/spec/interfaces/SPEC.md` 整份（`interfaces/world.py`、
   `interfaces/tools.py` 等六个文件**全都不存在**，那些 Port 现在住在各自的层里）。
   改 `AGENTS.md` 按规矩要先与你讨论，所以只列着。
   （**本次已顺手修的是 `docs/spec/tools/SPEC.md`**——它直接引用了协议旧地址，属于
   "这次改动造成的活引用失效"，和那两份"本来就过期"的不是一类，见 §7.2。）

---

## 7. 落地结果（2026-09-12）

### 7.1 三层各量一遍：为什么"只搬协议"或"只收窄出口"都过不了验收

`sys.modules` 增量，本机 3.12。**关键在"累计"那一列**——`tools/interface` 是
`tools` 的**子模块**，拿它就必须先跑完 `tools/__init__.py`：

| 做法 | 拿 `GameToolPort` 时连带的 `pokemon_agent` 模块 | 其中 `tools.*` |
|---|---|---|
| 基线（协议在 `tools/ports.py`，出口同时导出协议+实现） | **146** = 信封 113 + 33 | 8 个：5 插件 + `trace_render` + `ports` + 包本身 |
| 只搬协议、出口照旧急切导入插件 | **146**（纹丝不动） | 插件一个不少 |
| **搬协议 + 出口分家 + 实现懒加载（本次）** | **116** = 113 + 3 | `tools`、`tools.interface`、`tools.interface.ports`——**零插件** |
| 对照：只要信封 `schemas.harness` | 113 | 无 |

那 3 个是"门"本身的开销（包 + 协议包 + 协议文件），不是实现——**这是这条链的下限**，
再低就得让 `tools` 不是一个包了。v2 §5 验收 ① 写的"≈113"因此不够准确，实测是 **116**。

### 7.2 落地时发现的两件事（计划外，都留档）

1. **`tools/trace_tool.py` 的子模块 import 必须显式化。** 原来是
   `from pokemon_agent.tools import trace_render`。出口改懒之后这行**运行期仍然能跑**
   （`from 包 import 子模块` 在 `getattr` 失败后会回退去 import 子模块），但
   **`scripts/check_imports.py` 会判它失效**——它对 `from X import a, b` 只做
   `hasattr(X, "a")`，而 `hasattr` **不触发**那个子模块回退。它今天之所以没报错，
   纯粹是因为脚本按路径字母序先走到 `trace_render.py`、把该子模块绑成了包属性——
   **靠字母序侥幸通过**。改成 `import pokemon_agent.tools.trace_render as trace_render`
   之后，AST 上是纯 `Import` 节点，脚本只验"模块导得到"，不再依赖顺序。
   *教训*：**懒加载出口 + `from 包 import 子模块` 是一对危险组合**，判据不是
   "跑得起来"，而是"静态检查器看得懂"。
2. **`docs/spec/tools/SPEC.md` 比预想的更旧。** 它引用的 `interfaces/tools.py`、
   `interfaces/world.py`、`memory/port.py`、`memory/semantic/semantic_store.py`、
   `SemanticObjectStore` **今天全都不存在**，§2/§3/§5 的签名还是裸参时代
   （`MemoryTool` 的构造参数也从 `objects: SemanticObjectStore` 换成了
   `embedding_provider` + `reranker_provider` + 三个路径/上限参数）。
   按惯例**只加现状块 + 就地标注、不重写历史论证**——那份文档最值钱的是设计论证
   （为什么拆两个 Port、为什么掩码归 `GameTools`），那些没过期。

### 7.3 验收记录

| 闸 | 结果 |
|---|---|
| §5 验收 ① 拿协议的成本 | **146 → 116**，`tools.*` 零插件 |
| §5 验收 ② 没人再从 `tools/` 根拿协议 | **0 行** |
| §5 验收 ③ 插件只在装配点 new | 仅 `build.py`（外加既有的 `experiment/real_check/check_memory_roundtrip.py`，**改动前就如此**，非本次引入） |
| §5 验收 ④ 抽象不碰实现 | `tools/interface/` 内 **0 行** |
| `scripts/check_imports.py` | **OK 404 条**（条数不变——只换目标，没增删 import） |
| `scripts/check_graph_phases.py` | **OK 20 nodes**（图拓扑没碰） |
| 全包冒烟（逐模块 import） | **171 个模块，失败 0** |
| `ruff format --check`（动过的文件） | **15 files already formatted** |
| `ruff check .` | **54 → 55**，唯一新增是 `tools/__init__.py:66` 的 `ANN202` |

**关于 ruff 54 → 55 —— 这一条是结构性的，不是失误。** 仓里**已有五个**懒加载出口
（`world` / `brain` / `harness` / `brain.interface` / `harness.interface` 的
`__init__.py`），**每一个都贡献一条同款 `ANN202`**（`__getattr__` 缺返回注解）。
新加第六个懒加载包，就必然多一条。两条路：接受 55，或把六个 `__getattr__` 一起
加返回注解（可降到 49，但那是本任务之外的无谓改动）。**本次选接受**，并在此留痕，
免得下次被当成回归。
