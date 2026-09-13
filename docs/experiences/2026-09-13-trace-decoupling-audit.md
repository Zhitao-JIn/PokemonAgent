# trace 模块脱钩审计：按 P1～P7 清点「如何移出」

- 日期：2026-09-13
- 对标文档：`docs/experiences/2026-09-13-brain-decoupling-principles.md`（P1～P7）
- 关联 Issue：`AGENTS.md` 第 2 条铁律（四模块按独立第三方对待）
- 系统状态：**trace 本体已达 P1 终态**；待决的是 harness 里 7 个读点怎么重布线

---

## 一、结论先行（v2）

> **v2 修正说明**：用户 15:25 指出三处，全部证实、已改：
> ① `Source`/`EventType` **已经降级为裸 str**（v1 当成了"待拍板"）；
> ② **trace 项目无关，P3 判据不适用**（v1 结论对、判据错）；
> ③ **`TraceEvent` 移出 + trace 内部改用 `Event`**（v1 只说了"不该跟模块走"，
> 没说"trace 内部用什么"）。

| 原则 | 判定 | 说明 |
|---|---|---|
| **P1 拷得走** | ✅ **已达标** | `trace/` 对 `pokemon_agent.*` 外部依赖 = **0**。本体契约一行不用动 |
| **P2 依赖三分** | ⚠️ 有 2 处实现依赖 | `build.py` / `harness/episode/episode_frames.py` |
| **P3 异常继承** | ✅ **不适用**（项目无关） | trace 没有"另一层的词汇"可以翻译过去 |
| **P4 桥的位置** | ❌ **读侧无桥** | 写侧有 `TraceTool`；读侧 harness 直接 import trace（8 处） |
| **P5 同形不同约** | ✅ 不适用 | 无第二个同形协议 |
| **P6 信封本地化** | ✅ 已达标 | 且比 brain 彻底——连**不透明端口**边界都守住 |
| **P7 包初始化分层** | ⚠️ **v2 新发现真依赖** | `store.py:33` 拿 `__file__` 回溯三级算仓库根 |

**一句话**：**trace 的契约（`TracePort`）已经在外了，要移出的是
① harness 里 8 个读点、② 寄居在 `TraceEvent` 里的 7 个项目专属字段。**

**核心动作（v2）**：`TraceEvent` 里塞着 12 个字段，**trace 只用得到 6 个**。
把两者拆开——`Event`（trace 自己的，6 字段）留在 `trace/`，
`TraceEvent`（项目记账约定，11 字段）移去 `schemas/harness/domain/`。

---

## 二、P1：能不能整个拷走 —— ✅ 达标

### AST 审计（`ast.walk` 全树，含函数内 import）

`trace/` 包内四个文件的**全部** import：

```
pokemon_agent/trace/__init__.py          → .datastore / .interface / .store
pokemon_agent/trace/datastore/__init__.py → .trace_event
pokemon_agent/trace/datastore/trace_event.py → __future__ / typing / pydantic
pokemon_agent/trace/interface/__init__.py → __future__ / .trace_port
pokemon_agent/trace/interface/trace_port.py → __future__ / typing
pokemon_agent/trace/store.py → base64 / os / time / pathlib / typing / .datastore
```

**对 `pokemon_agent.*` 的外部依赖：0。** 非项目依赖只有标准库 + `pydantic`。

### 逐层核对

| 层 | 文件 | 外部依赖 | 结论 |
|---|---|---|---|
| 协议 | `trace/interface/trace_port.py` | 只有 `typing` / `__future__` | **零 import 契约**，是四模块里最干净的一张 |
| 实现 | `trace/store.py` | 标准库 + 自己的 `datastore` | 自持 |
| 形状 | `trace/datastore/trace_event.py` | `pydantic` + `typing` | 自持 |

### 与 brain 的对比

brain 达标时对外依赖归零的代价是「搬 `providers` 进脑内 + 复制四封信封进
`brain/schemas/` + 异常自成一根 `BrainError`」。**trace 这三件事一件都不需要**：

- 它本来就不持有任何 provider（不调模型）；
- 它本来就没有信封（`TracePort` 是不透明端口，签名里全是裸字段）；
- 它本来就没有异常家族。

**所以 trace 是 P1 的"零成本通过"案例**——它此前几轮（0913 的 `EventType`/`Source`
降裸 str、删 `cursor`/`read_disk_events`/`void_after`、`TraceKind` 搬去
`schemas/harness/`）已经把功课做完了，且做得比 brain 彻底。

### P7 为什么不适用

brain 需要懒加载是因为 `brain/__init__.py` 一导入就连带拉进厂商客户端 + `PIL`。
trace 的 `__init__.py` 拉进的只有 `pydantic`——**没有代价可省，不该加
`__getattr__`**（那会把"只想拿 `TracePort`"的调用方变复杂）。P7 的判据
（"只想声明型号的调用方不该背上网关客户端"）在这里无对象。

---

## 三、P2：依赖三类清点

### 第一类：实现依赖 —— 2 处

| 位置 | 代码 | 性质 |
|---|---|---|
| `build.py:31` + `:91` | `from pokemon_agent.trace import LocalTrace`；`trace = LocalTrace(run_id=…, event_sink=…)` | **装配点 new 实现**。与 `BrainTool.build()` 之前的 `build.py` 同形 |
| `harness/episode/episode_frames.py:19` + `:65` | `from pokemon_agent.trace import read_screenshot`；`raw = read_screenshot(deps.run_id, event_id)` | **真·越界**：harness 直接调 trace 的模块级函数 |

`build.py` 那一处有豁免争议（装配点有 new 的权限，见 `AGENTS.md` 第十二节）；
`episode_frames.py` 那一处**没有争议——它没有任何豁免**：harness 在探测阶段
（读第 `step` 步的便利截图、编 base64）**绕过 tool 层直接碰 trace 的文件系统函数**。

### 第二类：内部协议 / 内部词汇 —— 已在包内，✅

`EventType` / `Source` / `TraceEvent` / `TRACE_SCHEMA_VERSION` 全部住在
`trace/datastore/`。**这是三件套里唯一做对的一项**，且对 P1 有直接贡献。

### 第三类：形状引用 —— 15 处

见第五节完整清单。

---

## 四、P3 / P5 / P6 / P7：重新表述（v2 修正）

> ⚠️ **v1 这一节的推导链是错的，v2 重建。** v1 说"trace 不抛自定义异常 → 无债"，
> 结论碰巧对、但**判据用错了**：P3 的判据是"异常有没有跨过 tool 层这座桥"
> ——trace 作为不透明存储，**`append` 会因为磁盘、权限、空间、编码而真抛**，
> 它不能像 HTTP 服务那样把域错误映射成状态码，只能炸。真正让它不成立的是
> **调用约定**，不是"不抛异常"。

#### P3 对 trace **不成立**——判据本身不适用（用户 15:25 指出）

**P3 的完整判据**（brain 那一轮的原话）：*"异常继承判据 = 这条异常有没有
跨过 tool 层这座桥"*……**不是**"谁抛谁接"，**不是**"多模块共用"*。
它的两个前提：(a) 模块会主动抛出**带语义的域异常**；(b) 这个异常**需要被
tool 层翻译**成另一层的词汇。

**trace 两个前提都不成立**：

| | brain | trace |
|---|---|---|
| 会抛什么 | `ParseFailure` 家族——**语义丰富**（解析失败、动作越界…） | 全是基础设施错误：`OSError`（磁盘满/权限）、`UnicodeDecodeError`（残文件）、`ValueError`（重复 episode_id） |
| 调用约定 | 必须**重试**，所以 tool 层要 `except AttemptFailed` 接住、攒重试、耗尽翻译成 `MaxRetriesExceeded` | **调用方必须炸**——写不进去这件事没有"再试一次"的语义，也不能被吞 |
| 需要 tool 翻译吗 | **要**（brain 的词汇 → harness 的词汇） | **不要**——`OSError` 在两层是同一件事，翻译不出新信息 |

**所以**：trace 的异常**不是"还没跨过桥的域异常"，而是"注定要穿透所有层的
基础设施故障"**。给它建 `TraceError` 家族、让 tool 层接住再抛，是在
**把一部一层的失败伪装成两层的协议**——P4 警告的"两处表达同一件事 =
两处都可以被改坏"，正是这个形状。

**更深一层（这是 P3 不成立的根因）**：**trace 是项目无关的**。它的契约只有
"按时间记账"，它不知道 harness/brain/world 这些层存在，所以它根本
**没有"另一层的词汇"可以翻译过去**。P3 描述的是"两个互相认识的模块之间
的异常翻译"，而 trace 不认识任何人。

**结论**：P3 对 trace **不适用**，`trace/` 不该有异常家族，`TracePort` 也不该
在 docstring 里承诺异常语义。**这一块零改动。**

#### P5（同形不同约）：不适用

trace 没有第二个同形协议（`TracePort` 只有一个消费者群）。
P5 说的是"同一个物理能力被两个模块各自声明协议"（brain 的 `JudgeProvider`
vs world 的 `VisionProvider`）——trace 没有这种对应物。

#### P6（信封本地化）：**已达标，但 v1 的理由写窄了**

v1 说"trace 无信封所以无事可做"。**更准确的说法是：trace 是四模块里 P6 做得
最彻底的一个**——它连**不透明端口的边界**都守住了（`payload: dict[str, str]`），
不只是"没有信封"。`FromHarnessToTraceToolAppendModelCallsReq.py` 的 docstring
已把这条边界写死：

> `trace` 被当作**独立模块**对待——它只认自己的词表（`TraceKind`/`Source`/`EventType`）
> 与 `payload: dict[str, str]` 裸字段，不认识 `ModelCall` 这类业务类型；
> "业务账 → 裸字段"的转换整个留给 tool 层（`tools/trace/render.py`）。

**P6 真正的作用落在别处**：`Event`（新结构）要在 `trace/` 与 `schemas/harness/`
**双坐**，那一对副本才是本项目 P6 手法的下一个适用点（见 §6.6）。

#### P7（包初始化分层）：**v1 漏了一个真依赖**

v1 说"trace 的依赖都便宜，无需懒加载"。**这漏了 `trace/store.py:33`**：

```python
project_root = Path(__file__).parent.parent.parent   # ← 靠 __file__ 回溯三级
STORAGE_ROOT = project_root / "trace_data"           # ← 模块级副作用，import 即算
```

**它把"仓库在哪"这件事硬编码进了 trace 模块**——这是 v1 完全没点出的、
**与 `P1 拷得走` 直接冲突的一个真依赖**（拷到别的项目，数据会写进那个项目的
`trace_data/`）。对照 `memory/store.py` 的正确做法：

```python
# memory/store.py:95 —— root 从构造参数来，缺省才回退
base = pathlib.Path(root) if root is not None else _PROJECT_ROOT / "memory"
```

**修法**：`LocalTrace.__init__` 加 `root: str | Path | None = None`，
模块级 `STORAGE_ROOT` 降级为 `_DEFAULT_ROOT`（缺省回退）。这样
`build.py` 显式传路径（**唯一的装配点知道仓库在哪**），trace 自己不再假设。

---

## 五、P4 详查：桥只建了一半

### 现状：写侧有桥，读侧没有

```
harness 22 节点 ──(FromHarnessToTraceToolAppendReq 信封)──► TraceTool ──► TracePort ──► LocalTrace
                    ★ 这是桥（P4 合格）

harness 5 个读点 ──── 直接 import pokemon_agent.trace ────► LocalTrace / read_screenshot
                    ✗ 这是没有桥的越层
```

`tools/trace/__init__.py` 的 docstring 自己承认了这个不对称：

> **边界不对称**：写者只有 harness（走本端口）；读者是 api
> （运维侧，直读 `TracePort`/`LocalTrace`，不进 tool 层）。

"api 直读"说得过去（运维侧不经过 harness 图）；但 **harness 自己 5 个读点
绕道直读，就不是"边界不对称"，是"桥只建了一半"**。

### 全仓库对 trace 的 7 个模块外引用（逐个定性）

| # | 位置 | 拿什么 | 判定 |
|---|---|---|---|
| 1 | `api.py:85` | `TracePort` | 仅类型注解（`_RunHandle` 字段 + `create_app` 工厂签名）→ **`handle.trace` 全项目零读取点**（`grep '\.trace'` 只命中赋值那一行）。**删注解 + 删字段 = 零影响** |
| 2 | `build.py:31` | `LocalTrace` | 实现依赖（装配点），有豁免 |
| 3 | `harness/episode/episode_frames.py:19` | `read_screenshot` | ★ **实现依赖，真越界** |
| 4 | `harness/episode/close/verify_and_summarize.py:42` | `Source` | 形状引用（填信封字段） |
| 5 | `harness/episode/decide/think_action.py:33` | `Source` | 形状引用 |
| 6 | `harness/episode/gate/judge.py:23` | `Source` | 形状引用 |
| 7 | `harness/episode/press/perceive_after_action.py:50` | `Source` | 形状引用 |
| 8 | `harness/run/nodes/plan.py:43` | `EventType` + `Source` | 形状引用（**真读**：`RUN_TRACE_MASK = frozenset({EventType.LIFECYCLE, EventType.ERROR})`） |
| 9 | `harness/run/nodes/review.py:21` | `TraceEvent` | 形状引用（注解 + `ev.episode_id` 过滤） |
| 10 | `harness/run_data_center.py:35` | `TraceEvent` | 形状引用（**真构造容器**：`list[TraceEvent]` + `publish_event(event: TraceEvent)`） |
| 11 | `schemas/harness/communication/FromHarnessToBrainToolPlanOnceReq.py:13` | `TraceEvent` | 信封字段注解 ⚠️ |
| 12 | `schemas/harness/communication/FromHarnessToReviewerReviewReq.py:8` | `TraceEvent` | 信封字段注解 ⚠️ |
| 13 | `tools/prompts/run_plan.py:12` | `EventType` + `TraceEvent` | tool 层，**允许** |
| 14 | `tools/trace/__init__.py:36` | `TracePort` | tool 层，**允许** |
| 15 | `tools/trace/render.py:41` | `EventType` + `Source` | tool 层，**允许** |

**harness 侧真读点 = #3 #4 #5 #6 #7 #8 #9 #10 共 8 处**（含 `Source` 的 4 处填字段）；
`tools/` 3 处合法；`api.py` 1 处可删；`schemas/` 2 处是另一回事（见下节）。

### ⭐ 新发现：`TraceEvent` 是「信封里的数据形状」，不是「trace 的私有物」

> **v2 补充**：本节 v1 的定性（"双重身份：既是第二类又是第三类"）仍然成立，
> 但**结论要前进一步**——用户 15:25 定案：**把它移出，trace 内部改用 `Event`**。
> 也就是说不是"它该不该跟模块走"的犹疑，而是"**里面寄居了 7 个不属于 trace
> 的字段，该拆开**"。拆法见 §6.6。

**它有双重身份**：

1. **第二类（内部协议/词汇）**——`LocalTrace._scan_events()` 用
   `TraceEvent.model_validate_json()` **真的构造它**。按判据（模块自己的
   Port/实现真的需要构造或消费它的具体样子 ⇒ 归它）**满足**。
2. **第三类（形状引用）**——它同时出现在**信封字段注解**里：
   - `FromHarnessToReviewerReviewReq.episode_trace: list[TraceEvent]`
   - `FromHarnessToBrainToolPlanOnceReq.events: list[TraceEvent]`

**两条判据冲突了**，v2 的解法是**拆开而不是二选一**（见 §6.6）：
**trace 真的需要的那 6 个字段**做成 `Event` 留在 `trace/`；
**项目加的 7 个装饰字段**跟着 `TraceEvent` 移去 `schemas/harness/domain/`。

---

## 六、如何移出：先决条件 + 两套方案

### 6.1 真缺口：没有一个「批量读」的入口

`LocalTrace` 的**全部对外能力**只有：`append()` / `__init__()` /
模块级 `read_screenshot()` / `screenshot_filename()`。

**它没有任何"按 episode 读全量事件"的方法**——读端全在 harness：
`RunDataCenter.events()` 拿 `event_sink` 双写攒的内存表，
`review.py` 再在 Python 侧按 `episode_id` 筛。

**所以"把读点移出去"的先决条件是：给 trace 一个批量读 API。**
而实现它**必须**先解决记录形状从哪来——`_scan_events` 现在用的就是
`TraceEvent.model_validate_json()`：

```python
# trace/store.py:166-182（现状）
def _scan_events(self) -> list[TraceEvent]:
    for path in sorted(self._events_dir.glob("*.json")):
        event = TraceEvent.model_validate_json(path.read_text(encoding="utf-8"))
```

裸形状落位之后，`TracePort` 就是**三方法契约**：

```python
def append(episode_id, step, type, source, payload=None, frame_png=None) -> int
def read_events(episode_id: str | None = None) -> list[裸事件形状]
def read_event(event_id: int) -> 裸事件形状 | None
```

### 6.2 方案 A —— 长在现有 `TraceTool` 上（harness 零新增 Port）

```python
# tools/trace/__init__.py
class TraceTool:
    def __init__(self, trace: LocalTrace) -> None:   # 实现其实已经持有
        self._trace = trace

    def read_events(self, episode_id: str | None = None) -> list[TraceEvent]:
        """批量读事件，可按 episode 切片。"""
```

- 调用方（`run/nodes/review.py`、`run_data_center.py`、`episode_frames.py`）
  从 `deps.trace.read_events(...)` 读——**只认已有的 `TraceToolPort`**。
- `api.py` 删 `TracePort` 注解（它本来就没读 `handle.trace`）；
  `build.py` 返回的 `LocalTrace` 实例继续供运维侧/调试直读。
- **代价**：`TraceToolPort` 新增签名后要引用 `TraceEvent`，
  于是**新增一条 `schemas.harness → trace` 依赖**（`schemas.harness.domain.trace_event.py`）。

### ⚠️ 方案 A 的硬约束：必须先做「双坐搬家」否则循环导入

本轮实测踩到：`schemas/harness/communication/FromHarnessToBrainToolPlanOnceReq.py:13`
**直接** `from pokemon_agent.trace import TraceEvent`（不是从 `schemas.harness` 出口拿）。

一旦 `TraceToolPort.read_events()` 的签名写上 `list[TraceEvent]` 而 `TraceEvent` 又住在
`trace/datastore/`，而 `trace/store.py` 需要 `EventType` 做 episode_end 判断，
就会形成：

```
schemas.harness.__init__
  └─ communication.FromHarnessToBrainToolPlanOnceReq  (加载到第 13 行)
       └─ pokemon_agent.trace
            └─ pokemon_agent.schemas.harness   ← 半加载，环
```

**解法（双坐 `git mv`）**：

```bash
git mv pokemon_agent/trace/datastore/trace_event.py \
       pokemon_agent/schemas/harness/domain/trace_event.py
git mv pokemon_agent/trace/datastore/trace_event.py \
       pokemon_agent/tools/interface/trace_event.py      # 第二坐，逐字节相同
```

**为什么是双坐而不是单份**：
- 若只留 `schemas/harness/domain/`（改名 `schemas/harness/`）：trace **反向依赖**
  声明方的语言（agent 与 trace 能通过 trace 调用工具，但工具名与 schema 是 agent 的），
  且与 trace 零依赖的既定事实矛盾。
- 若只留 `tools/interface/`（改名 `tools/`）：`schemas` 会 import `tools`
  ——而 `tools/interface/ports.py` 现在**直接 import `schemas.harness`**，
  立刻成环。
- **双坐**：`schemas/harness/` 那份给信封用，`tools/interface/` 那份给 Port 用，
  两者逐字节相同、各自声明。**P6（信封本地化）的"两边各持一份 + 人工核对"**
  正是为这种场景立的。

配套改动（6 个文件）：两个信封、`plan.py`、`run_plan.py`、`review.py`、
`run_data_center.py` 的 `TraceEvent` import 全部改指新地址。

#### 6.5 方案 B —— 新增 `TraceReadToolPort`（边界更干净）

| 动作 | 位置 |
|---|---|
| **删** `api.py:85` 的 `from pokemon_agent.trace import TracePort` + `_RunHandle.trace` 字段 + 工厂签名里的 `TracePort` | 实测 `handle.trace` 零读取点，删了不影响 |
| `build.py` 返回值**只留 `LocalTrace`**（供 api/调试直读），不再经 `TracePort` 类型 | 与现状同 |
| `run/nodes/review.py`、`run_data_center.py`、`episode_frames.py` 改经新 Port 读 | 3 处 |
| 新增 `tools/interface/ports.py::TraceReadToolPort` | 1 张 |

- **收益**：`harness` 对 trace 的 import 从 8 处降到 **0**，
  `api.py` 也归零；`trace` 真正成为"只经 tool 层说话"的模块。
- **代价**：多一张 Port；`Event` 仍要解决双坐问题（照样需要）。

### 6.6 ★ `TraceEvent` 移出 + 内部改用 `Event`（用户 15:25 定案）

**两条指令**：

1. **`TraceEvent` 移出 trace** —— 它是"信封里的数据形状"，不该跟着模块走（见 §5）。
2. **trace 内部用新的组织数据结构 `Event`** —— 这才是 trace 自己的东西。

**为什么必须有 `Event`**（这是整个方案的技术支点）：

移出 `TraceEvent` 之后，trace 就**没有记录形状了**——而 `store.py` 现在**真的
在读它**：

```python
# trace/store.py:166-182（现状）
for path in sorted(self._events_dir.glob("*.json")):
    event = TraceEvent.model_validate_json(path.read_text(encoding="utf-8"))  # 构造它
    if event.type == EventType.LIFECYCLE and event.payload.get("kind") == "episode_end":
                                                     # 还要读它的字段
```

所以 `Event` **不是"改个名字"，是补上 trace 缺失的那块**——它必须装下
trace 真正用到的字段。清点下来是 **6 个**（v2.1 修正：v2 初稿漏了
`frame_png`，`_save_screenshot` 真的读它）：

| 字段 | trace 为什么必须知道 | 现状出处 |
|---|---|---|
| `event_id` | 分配单调 id（`_next_id`）、截图文件名 | `store.py:103` / `:162` |
| `episode_id` | `_episode_is_complete(episode_id)` | `store.py:76` |
| `step` | 落盘 + precondition `assert step >= 0` | `store.py:100` |
| `type` | `EventType.LIFECYCLE` 判 episode_end | `store.py:76` / `:136` |
| `payload.kind` | `== "episode_end"` 判完整收尾 | `store.py:76` |
| **`frame_png`** | **`_save_screenshot` 落 PNG 便利副本** | **`store.py:162-164`** |

**其余全是本项目加的业务装饰**，trace 一概不需要：`run_id`、`source`、
`phase`、`ts`、`valid`、`schema_version`、`model_config`
（`ser_json_bytes="base64"`）——这些**只对项目里的读端有意义**（SSE / 前端 /
reviewer），所以它们应该在**移出去的那个类**上。

#### 形状（建议）

```python
# trace/datastore/event.py —— trace 自己的记录组织
class Event(BaseModel):
    """一个事件。**trace 只认这六样**，其余都是项目的事。"""
    event_id: int
    episode_id: str
    step: int
    type: str        # 裸 str，见 §6.4
    payload: dict[str, str] = {}
    frame_png: str | None = None
```

```python
# schemas/harness/domain/trace_event.py —— 项目侧的事件（原 TraceEvent 移出）
class TraceEvent(Event):          # 或独立定义 + 逐字段同构
    """项目认识的 trace 事件：在 `Event` 之上加业务装饰。

    `source`/`run_id`/`phase`/`ts`/`valid`/`schema_version`
    和 `model_config` 的 base64 约定都住这里——**它们是项目的记账约定，
    不是 trace 的存储契约**。`frame_png` **不在这里**（trace 自己要用，见上表）。
    """
    run_id: str
    source: str
    phase: str = ""
    ts: float
    valid: bool = True
    schema_version: int = TRACE_SCHEMA_VERSION
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")
```

> **`frame_png` 归属的取舍**：它**两边都要**——trace 用它落截图副本、
> 项目用它做 SSE/前端。判给 `Event`（trace 侧），因为
> **"截图与事件共享 event_id"是 trace 自己的存储约定**（`store.py:191`
> 的 `screenshot_filename()` 就是这条约定的实现），而不是项目记账约定。

#### ⚠️ `Event` 必须**双坐**（否则回退成"trace 依赖 schemas"）

`TracePort` 的签名要写 `-> list[Event]`。它能不能直接
`from pokemon_agent.schemas.harness.domain import Event`？

**不能**——那就让 `trace/interface/trace_port.py` 反向依赖 `schemas.harness`
（**契约层**），正是 §6.2 那条成环警告的同一个形状。所以：

```
trace/datastore/event.py                     ← trace 的 Event（权威）
schemas/harness/domain/event.py              ← 逐字节相同的副本（供信封/Port 标注）
```

这是 **P6（信封本地化）手法的下一个适用点**：两边各持一份 + docstring 明写
"必须保持同构" + **改动时人工核对**（副本漂移只在运行时炸，编译器看不见）。

**但有两个更省的替代**，值得先评估：

| 替代 | 做法 | 评估 |
|---|---|---|
| **`Event` 做成 Protocol**（✅ **已验证可行、推荐**） | `trace/interface/event.py` 用 `@runtime_checkable Protocol` 声明那 6 个属性，`TraceEvent` **结构化满足**它 | **最优**——纯类型、零运行时依赖、**零重复定义**（不需要副本、不需要人工核对）、与铁律 4 一致。**本轮已实测**：pydantic 模型 `isinstance` 检查为 `True`，`-> list[Event]` 做返回类型标注正常 |
| **`Event` 做成鸭子类型** | `read_events()` 返回 `list[Any]`，`store.py` 用 `getattr` 读 | 最省事但**丢类型**，且违反"跨层数据一律 Pydantic"（铁律 5）——不推荐 |

**实测证据**（本轮跑的验证脚本，可复现）：

```python
@runtime_checkable
class Event(Protocol):
    event_id: int;  episode_id: str;  step: int;  type: str;  payload: dict[str, str]

# 一个字段更多的 pydantic 模型——结构化满足，不需要显式继承
class TraceEvent(BaseModel):
    event_id: int; run_id: str; episode_id: str; step: int; type: str
    source: str; payload: dict[str, str] = {}; frame_png: str | None = None
    ts: float; valid: bool = True; schema_version: int = 4

isinstance(TraceEvent(...), Event)   # → True ✅
```

**`Event` 是 Protocol ⇒ `trace/` 不持有任何本项目的具体类，
`schemas/harness/domain/trace_event.py` 是唯一的实体定义，
`trace/interface/` 与 `schemas/harness/` 之间不需要副本、不需要人工核对。**

**注意 `store.py` 仍要一个可 new 的具体类**——`_scan_events` 得把磁盘 json
解析成什么。两个选择：
- **(i)** `Event` 做成 **Protocol + 一个模块内私有 `_Event(BaseModel)`** 实现，
  `_scan_events` 用它解析；对外的 Port 签名用 Protocol。**推荐**（外面看到的是协议，
  里面用的是自己的小模型）。
- **(ii)** 走非-pydantic 的 `dataclass`，配 `json.loads` 手写解析。
  丢掉 pydantic 的校验/版本容错（现在残文件靠 `except Exception: continue` 兜），**
  不推荐**。

#### 调用链会变成什么样

```python
# ✗ 现状：trace 自己 new 项目的类，靠 pydantic 默认值静默补 7 个字段
event = TraceEvent(event_id=…, run_id=self._run_id, episode_id=…, step=…,
                   type=…, phase=type, source=…, payload=…, frame_png=…,
                   ts=time.time(), schema_version=TRACE_SCHEMA_VERSION)

# ✓ 改造后：trace 只 new 自己的 Event，不认识的字段一个字都不写
event = Event(event_id=…, episode_id=…, step=…, type=…, payload=payload or {})
```

```python
# tool 层（`tools/trace/`）：把 Event 补成 TraceEvent 交给 event_sink
def _to_trace_event(self, event: Event, *, source: str, frame_png: str | None) -> TraceEvent:
    return TraceEvent(**event.model_dump(), run_id=…, source=source,
                      phase=event.type, frame_png=frame_png, ts=time.time())
```

```python
# 读侧（harness/api）经工具读回 TraceEvent：
events: list[TraceEvent] = deps.trace.read_events(episode_id=…)   # 方案 A
```

`event_sink` 的类型从 `Callable[[TraceEvent], None]` 收窄成
`Callable[[Event], None]`（`RunDataCenter.publish_event` 可能要跟着调整）。

#### 一句话总结这条改造

**`TraceEvent` 里塞着 12 个字段，而 trace 只用得到 6 个**——这不是巧合，
是"存储契约"和"项目记账约定"被压在同一个类里的症状。`Event` 把两者分开：
trace 拿它要的 6 个，项目拿全部 12 个。

### 6.4 `EventType` / `Source` 怎么处理 —— **P2 第二类，归 trace 自己**（v2 修正）

> ⚠️ **v1 这一节写错了，v2 重写。** v1 说"建议不搬"，把它当成了一个可选的
> "待拍板"项；实际上**它们从 0913 降级起就已经是裸 `str`**，
> `Source`/`EventType` 常量类只是值域声明的便利，住在 `trace/datastore/`
> 是**正确且已完成的终态**。

#### 对 P2 三类账（用户 15:25 澄清）——trace 是项目无关的，不参与项目的语言

`TracePort.append(..., type: str, source: str, ...)` 的签名**已经是裸 str**
（`trace/interface/trace_port.py:27-35` 逐字核对）。`Source`/`EventType` 常量类
只是"给调用方一组拼写正确的字面量"，**trace 不认识它们**——trace 只保证
「按时间记账」，`type`/`source` 的值域是**声明方（harness/tool）**的事。

**P2 三类账重新表述**（v1 的表述是把本项目的心智外推了）：

| 类别 | 判据 | 在本项目里的实例 | 归属 |
|---|---|---|---|
| **第一类：实现依赖** | 会 `new` / 调它的具体函数 | `build.py` 的 `BrainTool.build()`、`build_vision_provider()` | **只允许出现在 tool 层 / 装配点** |
| **第二类：内部协议 / 内部词汇** | 拷走这个模块后它是必需品 | `EventType`/`Source`/`Event`/`TRACE_SCHEMA_VERSION` | **跟着模块走**（trace 的"词表"是它自己的领域协议，**不是项目的接口方言**） |
| **第三类：形状引用** | 只是类型标注 / 字段类型 | 33 处 `Action`/`Goal` 等 | 可接受，登记即可 |

**关键更正**：`EventType`/`Source` **不是第三类、也不需要"搬去哪里"**——
它们是**第二类**，原住地就是 `trace/datastore/`。v1 把它们拿去和 `TraceKind`
类比，是错的（见下）。

**另外要守住的一条**：`EventType` 与 `TraceKind` **不是同一个概念，别合并**
（`FromHarnessToTraceToolAppendModelCallsReq.py:16` 已澄清过）：
- `TraceKind`（harness 声明"我记哪一笔账"）→ `schemas/harness/domain/`，**已搬完**；
- `EventType`（trace 落盘时那条记录的 `type`）→ **留 trace**。
- 两者的对应关系在 `tools/trace/render.py`（渲染函数吐出 `(EventType, Source, payload)`）
  ——**桥上的转换**，位置正确。

**而 `EventType`/`Source` 的实现真的在用**（`P4` 的"桥"之外还有一层理由）：

```python
# trace/store.py:76 —— 真的读 EventType 判 episode_end
if event.type == EventType.LIFECYCLE and event.payload.get("kind") == "episode_end":
# trace/store.py:136 —— append 路径同样读
if type == EventType.LIFECYCLE and (payload or {}).get("kind") == "episode_end":
```

**结论**：`EventType`/`Source` 一行都不用动。**移出 trace 读点这件事
不依赖先搬词表**——两件事可以分开做、互不阻塞。

#### v1 的 `tools/trace/render.py` 处置——降级为可选，且建议不做

v1 建议把 `render.py` 里 49 处 `Source.X` / 27 处 `EventType.X` 改成裸字符串字面量，
以便 trace 只经一层 tool 说话。**v2 建议不做**，理由：

- `_LINK_NAME: dict[str, str]` 的 docstring 明写它**必须**与
  `BrainTool._attempt_loop("…")` 的实参、`*AttemptFailed` 的默认 `source`
  逐字相同，**分两处写就会静默漂移**——从 `Source` 派生是防漂移机制，不是耦合。
- 这是**纯风格改动、零行为收益**，而 `render.py` 的 payload 字段是**跨模块契约**
  （观测台前端按字段名渲染），动它是大风险小收益。
- 若将来真要让 `tools/trace/` 也零依赖 trace 包，正确做法是把 `EventType`/`Source`
  **双坐 replicate 一份到 `tools/trace/`**（P6 同款手法 + 人工核对），
  而不是原地写字面量（那会失去防漂移派生）。**单独立题，别顺手做。**

---

## 七、改动清单（v2）

| # | 文件 | 改动 | 依赖关系 |
|---|---|---|---|
| 1 | `trace/datastore/event.py` | **新增 `Event`**（6 字段：`event_id`/`episode_id`/`step`/`type`/`payload`/`frame_png`） | **最先** |
| 2 | `trace/datastore/trace_event.py` | `git mv` 出 trace → `schemas/harness/domain/trace_event.py`，改成"`Event` + 7 个业务装饰字段"，原地留 docstring 说明 | 依赖 1 |
| 3 | `schemas/harness/domain/event.py` | `Event` 的副本（**待定**：若 Protocol 方案验证通过则跳过） | 依赖 1、2 |
| 4 | `trace/store.py` | 改成 new/读 `Event`（**去掉 `run_id`/`source`/`phase`/`ts`/`model_config` 的写入**）；加 `root` 参数（见 §4 P7）；`_scan_events` 改读 `Event` | 依赖 1 |
| 5 | `trace/interface/trace_port.py` | 加 `read_events` / `read_event`；返回类型定 `Event` | 依赖 1、3 |
| 6 | `tools/trace/` | `Event` → `TraceEvent` 的补齐转换 + 读入口（**A**：长在 `TraceTool` 上／**B**：新 Port） | 依赖 4、5 |
| 7 | `harness/run/nodes/review.py` | `episode_trace_events` 改从 tool 读 | 依赖 6 |
| 8 | `harness/run_data_center.py` | `events()` 改从 tool 读；`publish_event` 收 `Event` 后补齐 | 依赖 6 |
| 9 | `harness/episode/episode_frames.py` | `read_screenshot` 改经 tool（或明确豁免） | 依赖 6 |
| 10 | `schemas/harness/communication/*` 2 个信封 | `TraceEvent` import 改指新地址 | 依赖 2 |
| 11 | `build.py` | `LocalTrace(root=…)` 显式传路径；返回值类型 | 依赖 4 |

**第 11 项是 v2 新增的**（v1 漏了 `trace/store.py` 的 `__file__` 三级回溯，
见 §4 P7）。

### 明确"不动"的四项（v2）

| 项 | 结论 |
|---|---|
| `EventType` / `Source` | **第二类，原住地就是 `trace/datastore/`**，一行不改（§6.4） |
| `tools/trace/render.py` 的 `Source.X` / `EventType.X` | **建议不改**——`_LINK_NAME` 的从 `Source` 派生是防漂移机制；要解耦应双坐 replicate 而非写字面量（§6.4） |
| `harness/` 4 处 + `plan.py` 的 `Source`/`EventType` 引用 | **登记即可**（第三类形状引用）。`Source` 横跨 harness 与 tool（render 用 49 次），不像 `TraceKind` 那样单消费者——**别顺手搬** |
| `trace/` 的异常面 | **P3 不成立**（§4），不加异常家族、不在 docstring 承诺异常 |

---

## 八、可复现的核对方法

```bash
PY="C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe"

# ① trace 本体对外依赖审计（应为零）
#    ast.walk 全树，收集 Import/ImportFrom 的 module，过滤 pokemon_agent.*

# ② 全仓库对 trace 的引用清点（按用途分类）
#    实现依赖 = 名字出现在 ast.Call.func；注解 = 出现在 AnnAssign.annotation

# ③ 逐模块独立解释器导入（唯一抓得到循环导入的方法）
#    注意：仓库内 .venv 是 linux 版，不可用；managed 3.13 缺依赖。

# ④ 双坐同构核对（P6 兜底）——两副本 model_fields 逐字段比对
```

**教训（本轮）**：`grep` 找不出"这个 import 是用来调还是用来标注"——
`api.py:85` 那处 `TracePort` 看起来像真依赖，实际 `handle.trace` 全项目零读取点。
**要么 AST + 用途分析，要么读到调用点为止。**

---

## 九、验收（v2）

- AST 审计：`trace/` 对 `pokemon_agent.*` 外部依赖 **0**（外部仅标准库 + `pydantic`）。
- 模块外引用清点：**19 处 → harness 8 / tools 3 / api 1 / schemas 2 / build 1**
  （另有 4 处是 docstring 散文，非 import）。
- 逐字核对：`TracePort.append` / `LocalTrace.append` 的 `type`/`source`
  **均为裸 `str`**（`trace_port.py:27-35`、`store.py:79-87`）。
- `Event` 字段面核对：trace 实际读到的事件字段**只有 6 个**
  （`store.py:76`/`:100`/`:103`/`:136`/`:162`/`:164`，逐个来源已列在 §6.6）。
- 被消费的 `TraceEvent` 字段全集（移出后仍要保留）：
  `event_id`（api:545-547）/ `type`（run_data_center:90）/ `episode_id`
  （review:37）/ `payload`（run_plan:31-38）/ `model_dump_json()`（api:546）。
- 未跑真实 harness（按规矩由用户运行）；未发真实 API 请求。
- **本轮仍未改任何代码**——v2 是在 v1 审计文档上的修正，不含落地改动。

## 十、待用户拍板的三件事

1. **`Event` 与 `TraceEvent` 的关系**：`TraceEvent` 继承 `Event`，
   还是两份独立定义？**若 `Event` 走 Protocol 方案则此问题自动消解**
   （`TraceEvent` 只是结构化满足协议，不存在继承或同构问题）。
2. **`Event` 的副本策略**：Protocol（推荐先验证）／双坐 replicate／鸭子类型。
3. **方案 A vs B**（读入口长在现有 `TraceTool` 上，还是新开 `TraceReadToolPort`）。
