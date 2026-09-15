# trace 脱钩：非 tool 引用清零

- 日期：2026-09-13
- 上游审计：`docs/experiences/2026-09-13-trace-decoupling-audit.md`（v2）
- 对标原则：`docs/experiences/2026-09-13-brain-decoupling-principles.md`（P1～P7）
- 关联铁律：`AGENTS.md` 第 2 条
- 状态：**方案已定，待执行**

> **本文件是 v2。** v1（同路径上一版）的目标是"harness 只剩 4 处 `EventType`/`Source`
> 形状引用、登记即可"；**本版收紧为"非 tool 引用一律为 0"**。
> 差异都来自用户 16:30 的一句定调：**trace 只该被 tool 层引用**。
> 两版冲突处，以本版为准。

---

## 0. 目标与判定

### 0.1 目标（一句话）

**全仓库对 `pokemon_agent.trace` 的 import，只允许出现在 `tools/` 下。**

判定只有一条命令，不需要解释：

```bash
grep -rn "from pokemon_agent.trace\|import pokemon_agent.trace" pokemon_agent/ \
  --include=*.py | grep -v "^pokemon_agent/tools/"
# 期望：无输出
```

**为什么是 `tools/` 而不是别的层**：`tools/` 是"harness 伸向各模块的手"，
它**默认认识两边的形状**（`AGENTS.md` 第二节：跨模块的数据交换只能发生在 tool 层）。
trace 是独立第三方模块，harness / schemas / api / build 都**不该认识它**——
它们只能认识 tool 层给的门面（`TraceToolPort`）与自己的契约层（`schemas.harness`）。

### 0.2 入边账（AST 实测，15 条）

**出边已经是 0**（trace 对 `pokemon_agent.*` 零外部 import，本次一行不动）。
要清的只有入边：

| # | 来源 | 条数 | 符号 | 判定 |
|---|---|:---:|---|---|
| 1 | `tools/` | 3 | `TracePort`(`trace/__init__.py:36`)、`EventType,Source`(`render.py:41`)、`EventType,TraceEvent`(`prompts/run_plan.py:12`) | ✅ **保留**（就是桥） |
| 2 | `harness/` | 8 | `read_screenshot`(`episode_frames.py:19`)、`TraceEvent`(`review.py:21`、`run_data_center.py:35`)、`EventType,Source`(`run/nodes/plan.py:43`)、`Source`×4（`episode/close/verify_and_summarize.py:42`、`episode/decide/think_action.py:33`、`episode/gate/judge.py:23`、`episode/press/perceive_after_action.py:50`） | ❌ **清零** |
| 3 | `schemas/` | 2 | `TraceEvent`（`communication/FromHarnessToBrainToolPlanOnceReq.py:13`、`FromHarnessToReviewerReviewReq.py:8`） | ❌ **清零**（契约层反向依赖） |
| 4 | `build.py` | 1 | `LocalTrace`（`:30`） | ❌ **清零** |
| 5 | `api.py` | 1 | `TracePort`（`:85`） | ❌ **清零**（死码） |

**12 条要清、3 条保留。**

### 0.3 两条边界（沿用 v1，不变）

1. **`trace_data/` 跟着启动位置走**——不引入 `root` 参数、不改 `STORAGE_ROOT` 算法。
   **已核实**：`trace/store.py:33` 的 `Path(__file__).parent.parent.parent` 与
   `memory/store.py:58` 的 `.resolve().parents[2]` **结果完全等价**（都指向仓库根）。
   现有算法本来就对，**这一块一行不动**。
2. **不改任何业务行为**——payload 字段格式、event_id 分配、截图命名、
   `event_sink` 语义、落盘 json 的键集合，全部逐字节不变。

---

## 1. 最终形状

### 1.1 三条事件形状，各归其位

```
pokemon_agent/trace/interface/event.py               ← Event（Protocol，6 属性）
    trace 声明"我要什么形状"，不持有任何具体类

pokemon_agent/trace/datastore/event.py               ← _Event（trace 私有具体实现）
    store.py 真的 new / 解析它；模块内私有，不进 __all__

pokemon_agent/schemas/harness/domain/trace_event.py  ← TraceEvent（从 trace 移出）
    项目记账约定：11 个业务字段；结构化满足 Event 协议（零显式依赖）
```

**为什么是 Protocol 而不是副本**（v1 已实测）：

```python
@runtime_checkable
class Event(Protocol):
    event_id: int;  episode_id: str;  step: int
    type: str;  payload: dict[str, str];  frame_png: str | None

class TraceEvent(BaseModel):        # 字段更多，结构化满足
    event_id: int; run_id: str; episode_id: str; step: int; type: str
    source: str; payload: dict[str, str] = {}; frame_png: str | None = None
    ts: float; valid: bool = True; schema_version: int = 4

isinstance(TraceEvent(...), Event)   # → True ✅（实测）
```

`Event` 是纯类型 ⇒ **不需要双坐副本、不需要人工同构核对**，
`trace/` 与 `schemas/` 之间零 import。

### 1.2 词表四件的归处（本版的关键变化）

| 件 | 现住 | 新住 | 判据 |
|---|---|---|---|
| `TraceKind` | `schemas/harness/domain/` | **不动** | 已搬完（harness 声明"我记哪一笔账"） |
| `Source` + `SourceName` | `trace/datastore/trace_event.py` | **→ `schemas/harness/domain/source.py`** | **trace 完全不消费它**；取值全是本项目的层名 |
| `EventType` + `EventTypeName` | `trace/datastore/trace_event.py` | **留 trace** | `trace/store.py:76,136` **真的消费**它（判收尾） |
| `TRACE_SCHEMA_VERSION` | `trace/datastore/trace_event.py` | **两份**（trace 一份、schemas 一份） | 见 §3 步骤 3 的成环约束 |

**`Source` 为什么必须走**——两条独立证据都指向同一个结论：

1. **判据（谁消费）**：AST 扫描 `trace/` 全包，对 `Source` 的引用**只有一处
   docstring**（`interface/trace_port.py:10`），`store.py` 零引用。
   一个没有消费者的类不构成"实现依赖"，按 P2 归类它就不是 trace 的。
2. **语义**：它的取值逐条写着本项目的层名——
   `PERCEPTION`(# 视觉模型这条链)、`DECISION`(# 只有 think_action 的 choose)、
   `HARNESS`、`WORLD`、`JUDGE`、`VERIFY`、`MEMORY`、`PLAN`(# **run 级规划器
   （RunHarness.plan）**)。**最后一个的注释里直接写着类名**——通用 trace 库
   不可能认识 `RunHarness`。它是**项目的记账词表**，跟 `TraceKind` 同类。

**`EventType` 为什么留**——`store.py` 真的读它：

```python
# trace/store.py:76
if event.type == EventType.LIFECYCLE and event.payload.get("kind") == "episode_end":
# trace/store.py:136（append 路径同样读）
if type == EventType.LIFECYCLE and (payload or {}).get("kind") == "episode_end":
```

它是 trace 的"这一段收尾了吗"的判定依据 ⇒ 有实现消费者 ⇒ 归 trace。
（**若将来要做到 trace 零项目词汇**，得把"收尾判定"参数化成构造参数——
那是一个单独立题，**不在本方案内**，见 §7。）

### 1.3 字段归属表（移出 `TraceEvent` 的依据）

| 字段 | 归 `Event` | 归 `TraceEvent` | 依据 |
|---|:---:|:---:|---|
| `event_id` | ✅ | | `_next_id` 分配；截图文件名 |
| `episode_id` | ✅ | | `_episode_is_complete()` |
| `step` | ✅ | | 落盘；`assert step >= 0` |
| `type` | ✅ | | `EventType.LIFECYCLE` 判 episode_end |
| `payload` | ✅ | | `payload["kind"] == "episode_end"` |
| `frame_png` | ✅ | | `_save_screenshot()` 落 PNG 副本 |
| `run_id` | | ✅ | 只有项目读端用（manifest join / 前端） |
| `source` | | ✅ | 只有项目读端用（成本拆分 / 失败归因） |
| `phase` | | ✅ | `store.py` 写的是 `type` 的字面值复制 |
| `ts` | | ✅ | 延迟统计；trace 不读 |
| `valid` | | ✅ | 历史数据兼容；trace 不读 |
| `schema_version` | | ✅ | 版本声明；trace 只写不读 |
| `model_config`(base64) | | ✅ | 项目落盘约定 |

**判据**：凡 `trace/store.py` **真的读或真的算**的字段 → `Event`；
只被写入、只被项目读端消费的 → `TraceEvent`。

---

## 2. 12 条怎么消：逐条机制

### 2.1 总表

| # | 边（文件:行 → 符号） | 机制 | 改成什么 |
|:--:|---|---|---|
| 1 | `harness/run_data_center.py:35` → `TraceEvent` | **M1** 形状搬家 | `from pokemon_agent.schemas.harness import TraceEvent` |
| 2 | `harness/run/nodes/review.py:21` → `TraceEvent` | M1 | 同上 |
| 3 | `schemas/.../FromHarnessToBrainToolPlanOnceReq.py:13` → `TraceEvent` | M1（**解环**） | `from pokemon_agent.schemas.harness.domain import TraceEvent` |
| 4 | `schemas/.../FromHarnessToReviewerReviewReq.py:8` → `TraceEvent` | M1（**解环**） | 同上 |
| 5 | `harness/episode/close/verify_and_summarize.py:42` → `Source` | **M2** 词表搬家 | `from pokemon_agent.schemas.harness import Source` |
| 6 | `harness/episode/decide/think_action.py:33` → `Source` | M2 | 同上 |
| 7 | `harness/episode/gate/judge.py:23` → `Source` | M2 | 同上 |
| 8 | `harness/episode/press/perceive_after_action.py:50` → `Source` | M2 | 同上 |
| 9 | `harness/run/nodes/plan.py:43` → `EventType, Source` | M2 + **M3** | `Source` 走 schemas；`EventType` 那半**删掉** |
| 10 | `harness/episode/episode_frames.py:19` → `read_screenshot` | **M4** 读能力上桥 | `deps.trace.read_screenshot(event_id)` |
| 11 | `build.py:30` → `LocalTrace` | **M5** 装配走工厂 | `TraceTool.build(...)` |
| 12 | `api.py:85` → `TracePort` | **M6** 删死码 | 删 import + 字段 + 签名类型 |

### 2.2 M1 —— `TraceEvent` 搬去契约层（消 4 条）

`TraceEvent` 有双重身份：`LocalTrace._scan_events()` 真的 `model_validate_json`
构造它（第二类），同时它是**两个信封的字段类型**（第三类形状引用）。
两条判据指向同一个原住地 `schemas/harness/domain/`，跟 memory 三件同类，
只是多一层理由：**它还出现在信封里**。

**为什么必须搬**：不搬的话 `schemas/harness/communication/*` 会**反向依赖实现包**
——契约层被实现层反向依赖，是本项目已明令禁止的
（`CHANGELOG.md` 深夜七第 5 条）。

搬完之后，harness 与 schemas 都从 `schemas.harness` 拿它——**那是它们本来就认识的那层**。

### 2.3 M2 —— `Source` 搬去契约层（消 5 条 + `plan.py` 的一半）

`Source` 搬去 `schemas/harness/domain/source.py`（与 `SourceName` 一起，逐字节不动，
只改 docstring 的口径：从"trace 的词表"改成"本项目的生产者词表"）。

搬完之后：
- harness 5 处 `from pokemon_agent.schemas.harness import Source`；
- `tools/trace/render.py:41` 的 `Source` 改从 `schemas.harness` 拿
  （`EventType` 那半**不动，仍从 trace 拿**）；
- **`_LINK_NAME: dict[Source, str]` 的防漂移机制照旧生效**（它派生自 `Source` 类，
  与 `Source` 住哪无关）——这是 v1 里我拿它当"Source 该留 trace"的理由，
  **那个理由不成立**：防漂移靠的是"从一个类派生"，不是"类住在 trace"。

### 2.4 M3 —— `RUN_TRACE_MASK` 删掉（消 1 条）

`harness/run/nodes/plan.py:48`：

```python
RUN_TRACE_MASK = frozenset({EventType.LIFECYCLE, EventType.ERROR})
```

**本版实测结论：它是死配置，直接删。**

理由是它下游的消费者自己已经筛过了。`req.events` 在本项目**只有一个消费点**：

```python
# tools/brain_tool.py:440
history = run_plan_prompt.history_lines(req.events)

# tools/prompts/run_plan.py:29-42（history_lines 内部）
for ev in events:
    kind = ev.payload.get("kind", "")
    if ev.type == EventType.LIFECYCLE and kind == "episode_start": ...
    elif ev.type == EventType.LIFECYCLE and kind == "episode_end": ...
```

它**只读 `LIFECYCLE` 的 `episode_start`/`episode_end`**——
mask 里的 `EventType.ERROR` 那半**从来没有被任何消费点读过**；
mask 的 `LIFECYCLE` 那半也只是提前扔掉了 `history_lines` 本来就会跳过的噪声。
**删掉 mask 后 `history_lines` 的输出逐字节不变。**

改动：

```python
# harness/run/nodes/plan.py
- from pokemon_agent.trace import EventType, Source
+ from pokemon_agent.schemas.harness import Source
...
- RUN_TRACE_MASK = frozenset({EventType.LIFECYCLE, EventType.ERROR})
- """...（口径说明）..."""
...
- events = data_center.events(RUN_TRACE_MASK)
+ events = data_center.events()
...
- __all__ 里去掉 "RUN_TRACE_MASK"
```

连带：`harness/run/nodes/__init__.py:21,31` 去掉 `RUN_TRACE_MASK`；
`FromHarnessToBrainToolPlanOnceReq` 的 docstring（"按 `RUN_TRACE_MASK` 过滤过的"）
改成"该 run 的全量事件流，渲染层按需要的口径自筛"。

⚠️ **代价**：`req.events` 从"mask 后"变成"全量"，`history_lines` 的循环从 O(k)
变 O(N)。**这是同一个进程内的列表浅拷贝**（`RunDataCenter.events()` 返回
`list(self._events)`），不复制事件对象，长 run（万级事件）下也就是多几次指针遍历。
**可接受。**

**保守替代**（若你想留住"显式口径"这个声明）：把 `RUN_TRACE_MASK` 搬进
`tools/prompts/run_plan.py`，在 `history_lines` 入口先筛一遍——harness 仍传全量，
"口径"由渲染层持有（它本来就是"渲染历史要哪些家族"的知识）。
**不推荐**，因为它与上面的三行代码是同一件事，只是换了个地方写死。

### 2.5 M4 —— 读能力上桥（消 1 条）

`harness/episode/episode_frames.py:19,65` 现在**直接调模块级函数**
`read_screenshot(deps.run_id, event_id)` ——**无任何豁免的真越界**
（它是 episode 图内的节点，属 harness 本体）。

**改法**：`TraceToolPort` 加一个方法，`TraceTool` 转调 trace：

```python
# tools/interface/ports.py :: TraceToolPort
def read_screenshot(self, event_id: int) -> bytes | None:
    """读某条事件的截图副本（人眼可读的那份 PNG），读不到返回 `None`。

    前置条件：无。
    后置条件：有则返回原始 PNG 字节；无则 `None`（"这一帧本来就没落图"
        是正常情形，不是错误）。
    """
    ...

# tools/trace/__init__.py :: TraceTool
def read_screenshot(self, event_id: int) -> bytes | None:
    return self._trace.read_screenshot(self._run_id, event_id)
```

```python
# harness/episode/episode_frames.py
- from pokemon_agent.trace import read_screenshot
...
- raw = read_screenshot(deps.run_id, event_id)
+ raw = deps.trace.read_screenshot(event_id)
```

`run_id` 由 tool 层持有（`TraceTool` 构造时接），harness 不再管——
这本来也是"路径拼装"的知识，属 tool 层。

### 2.6 M5 —— 装配走工厂（消 1 条）

抄 brain 的定案：**装配点 `build.py` 对模块零 import**
（`BrainTool.build()` / `build_vision_provider()` / `MemoryTool.build()` 已经是这个形状）。

**新增** `TraceTool.build()`：

```python
# tools/trace/__init__.py
@classmethod
def build(
    cls,
    *,
    run_id: str = "local",
    event_sink: Callable[[Event], None] | None = None,
) -> "TraceTool":
    """接线工厂：造 `LocalTrace` 并包成 `TraceTool`。

    **这是全项目唯一 import `LocalTrace` 的地方**（装配点只递裸字段）。
    与 `BrainTool.build()` / `MemoryTool.build()` / `build_vision_provider()` 同形。
    """
    from pokemon_agent.trace import LocalTrace      # 函数内 import：tool 层是唯一允许者
    return cls(LocalTrace(run_id=run_id, event_sink=event_sink), run_id=run_id)
```

```python
# build.py
- from pokemon_agent.trace import LocalTrace
...
- trace = LocalTrace(run_id=run_id, event_sink=data_center.publish_event)
- trace_tool = TraceTool(trace)
+ trace_tool = TraceTool.build(run_id=run_id, event_sink=data_center.publish_event)
```

**同时把 `build_real()` 返回值里的 `trace` 去掉**：

```python
# 前
) -> tuple[RunHarness, LocalTrace, PyBoyWorld, GameTools]:
    return run_harness, trace, world, game
# 后
) -> tuple[RunHarness, PyBoyWorld, GameTools]:
    return run_harness, world, game
```

理由：`build_real` 的返回 `trace` **两个调用方都把它解包后不用**——
`api.py:313` 拿它只为填 `_RunHandle.trace`（**全项目零读取点**，见 M6），
`experiment/real_check/check_harness.py:43` 解包后从未引用。
**这就是它必须删的原因**：留着它就必然要在签名里写一个 trace 类型。

连带三处：
- `api.py`：`build()` 与 `build_run` 的签名从 4 元组改 3 元组 `(harness, world, frames)`；
- `api.py` 的 `_RunHandle.trace` 字段删（M6）；
- `experiment/real_check/check_harness.py:43`：`harness, world, tools = build_real(...)`。

### 2.7 M6 —— 删死码（消 1 条）

`api.py:85` 的 `from pokemon_agent.trace import TracePort` 与它的三个用处全是死码。
**实测**：`handle.trace` 全项目**零读取点**（只有 `:166` 的赋值），
SSE 端点读的是 `handle.data_center.events()`（`:552`）。

改动：
- 删 `:85` 的 import；
- 删 `_RunHandle` 的 `trace: TracePort` 参数（`:157`）与 `self.trace = trace`（`:166`）；
- 删 `build_run` 签名里的 `TracePort`（`:284`、`:299`、`:307`）；
- `:372-376` 的 `handle = _RunHandle(run_id=..., trace=trace, ...)` 去掉 `trace=`；
- docstring 纠正：`:531` 的"轮询 LocalTrace"→"轮询 `RunDataCenter` 的事件槽"。

**零行为影响**：api 读事件一直是走 `data_center`，从没读过 trace。

---

## 3. 逐文件改动清单

顺序即依赖顺序。**每步可独立验证、独立提交。**

### 步骤 1 —— 新建 `Event` 协议（纯新增）

**新增** `pokemon_agent/trace/interface/event.py`：

```python
"""`Event`：trace 眼里的"一个事件"。

**是 Protocol，不是实体**——trace 只声明它需要什么形状，
不持有任何一个本项目的具体类。任何满足这六个属性的对象都是 `Event`，
所以项目里的 `TraceEvent`（字段更多、带业务装饰）结构化满足它，
**既不需要显式继承、也不需要副本**。

这六个属性是 `store.py` 真的读/真的算的全部。

`type`/`payload` 的值域由**声明方**定义，trace 不认识——
它只保证按时间记账（见 `TracePort` 的 docstring）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Event(Protocol):
    """一个事件的最小形状：trace 记账真正需要的那六样。"""

    event_id: int
    """全局单调递增的整数。trace 靠它分配下一个 id、命名截图副本。"""

    episode_id: str
    """所属的一段。trace 靠它回答"这一局收尾了吗"。"""

    step: int
    """发生在第几步。trace 只用它做 `assert step >= 0`（precondition）。"""

    type: str
    """事件种类（裸 str，取值由声明方定义）。
    trace 靠它认 `EventType.LIFECYCLE`。"""

    payload: dict[str, str]
    """该类型的结构化内容。trace 只读 `payload["kind"]`。"""

    frame_png: str | None
    """base64 的原始画面，多数事件为 None。
    trace 靠它决定要不要另存截图副本。"""
```

**改动** `trace/interface/__init__.py`：re-export `Event`，
`__all__ = ["Event", "TracePort"]`。

### 步骤 2 —— 建 trace 私有的具体实现

**新增** `pokemon_agent/trace/datastore/event.py`：

```python
"""`_Event`：`Event` 协议的具体实现，**trace 包私有**。

为什么必须有：`store.py` 要把磁盘上的 json 解析成一个对象、也要 new 一个对象
来落盘——协议声明不了"怎么构造"，所以需要一个具体类。
它是 trace 自己的，所以字段**只有那六个**，一个都不多。

**`extra="allow"`**：项目读端需要的装饰字段（`source`/`ts`/`valid`/…）
trace 不解释，但**不能丢**——落盘要写回去、读回来要交回 tool 层。
allow 让它们挂在 `model_extra` 上随行。

**不进 `__all__`**：外部一律通过 `Event` 协议说话。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Event(BaseModel):
    """trace 自己的事件。字段与 `trace/interface/event.py::Event` 一一对应。"""

    model_config = ConfigDict(extra="allow")

    event_id: int = Field(description="全局单调递增")
    episode_id: str = Field(description="所属的一段")
    step: int = Field(description="发生在第几步")
    type: str = Field(description="事件种类（裸 str，取值由声明方定义）")
    payload: dict[str, str] = Field(default_factory=dict)
    frame_png: str | None = Field(default=None, description="base64 的原始画面")
```

**注意**：`_Event` **不声明** `ConfigDict(ser_json_bytes="base64")`——
那是项目的落盘约定，跟着 `TraceEvent` 走。`frame_png` 两边都已是 `str | None`
（base64 文本），**行为不变**。

### 步骤 3 —— `TraceEvent` 移出 + 拆字段

`TraceEvent`（`trace/datastore/trace_event.py:82` 起）**移去**
`pokemon_agent/schemas/harness/domain/trace_event.py`。

**内容改造**：

1. **只带 `TraceEvent` 走**；`Source`/`SourceName`/`EventType`/`EventTypeName`/
   `TRACE_SCHEMA_VERSION` 的**定义留在原址**（见步骤 4、5）。
2. **删掉**移给 `Event` 的六个字段，改成结构化满足协议：

```python
"""项目认识的 trace 事件：本项目的记账约定。

**为什么住在这里**：`TraceEvent` 是**跨层数据形状**——它出现在
`FromHarnessToReviewerReviewReq.episode_trace` 和
`FromHarnessToBrainToolPlanOnceReq.events` 两个信封里。契约层不能反向依赖
实现包（`CHANGELOG.md` 深夜七第 5 条），所以它归 `schemas/harness/domain/`。

**与 `trace.Event` 的关系是"结构化满足"，不是继承**：本类**不 import**
`pokemon_agent.trace` 的任何东西——只是字段结构对得上，鸭子类型自洽。
（实测 `isinstance(TraceEvent(...), Event) is True`。）

**前六个字段是 trace 的存储契约**（`Event` 协议里声明）；
**后几个是项目的记账装饰**，只有项目读端（SSE / 前端 / reviewer / 统计）消费。
改动公共字段必须同步两侧——没有编译器保护。
"""


class TraceEvent(BaseModel):
    """一条已落盘的项目事件。"""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    # ---- trace 的存储字段（与 `trace.Event` 协议逐字段同构）----
    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(description="哪一次实验。**manifest 的 join key**")
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: str = Field(description="事件种类（见 `EventType` 的常量）")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    frame_png: str | None = Field(default=None, description="这一步感知到的原始画面")

    # ---- 项目的记账装饰（trace 不读）----
    phase: str = Field(default="", description="循环阶段。由事件类型推导")
    source: str = Field(description="由哪一层产生（见 `schemas.harness.Source` 的常量）")
    ts: float = Field(description="Unix 时间戳，秒")
    valid: bool = Field(default=True, description="属不属于有效时间线")
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)
```

3. **`TRACE_SCHEMA_VERSION` 必须复制成两份常量**（⚠️ **v1 已实测，import 会成环**）：

   ```
   schemas.harness.__init__
     └─ domain.trace_event  (import TRACE_SCHEMA_VERSION)
          └─ pokemon_agent.trace.__init__
               └─ trace.store
                    └─ pokemon_agent.schemas.harness.domain   ← 半加载，ImportError
   ImportError: cannot import name 'TraceEvent' from partially initialized
                module 'pokemon_agent.schemas.harness.domain'
   ```

   ✅ **正确做法**：`schemas/harness/domain/trace_event.py` **本地声明**
   ```python
   TRACE_SCHEMA_VERSION = 4
   """事件形状的版本号。**与 `trace/datastore` 的那份必须同值**——
   两边各持一份，改动时人工核对（代价只有一个 int）。"""
   ```
   `trace/datastore/trace_event.py` 保留它自己那份（trace 的落盘版本号）。

   ⚠️ **这是本方案唯一的硬约束**：`schemas/harness/domain/` 下的任何文件
   **不许 import `pokemon_agent.trace`**——一个 int 也不行。

**改动** `schemas/harness/domain/__init__.py`：
`__all__ = ["Source", "TraceEvent", "TraceKind"]`。
**改动** `schemas/harness/__init__.py`：加 `from .domain import Source, TraceEvent`。

### 步骤 4 —— `Source` 移去契约层

**新增** `pokemon_agent/schemas/harness/domain/source.py`：把
`trace/datastore/trace_event.py:24-51` 的 `Source` 与 `SourceName`
**逐字节搬过来**，只改 docstring 的口径：

```python
"""本项目的"生产者"词表：一条事件由哪条链产出。

**为什么住在这里**：它的取值全是**本项目的层名**（`perception`/`decision`/
`harness`/`world`/`judge`/`verify`/`memory`/`plan`）——通用的事件存储不可能
认识 `plan` 是"`RunHarness.plan`"、`verify` 是"蒸馏前把关"。
它跟 `TraceKind` 同类：**都是本项目声明"我记的是哪一笔账"**。

**为什么不在 `trace/`**：`trace/` 全包对 `Source` 零引用（`store.py` 只读
`EventType`）。一个没有实现消费者的类不构成 trace 的契约——按"归属看谁消费"，
它的消费者是 harness（填信封）与 tool 层（渲染 payload），所以归契约层。

**是字符串常量，不是枚举**（0913 降级）：磁盘上一直是裸字符串，
`TracePort` 的签名收裸 `str`——本类只是"给调用方一组拼写正确的字面量"。

**`_LINK_NAME` 的防漂移机制不受影响**：`tools/trace/render.py` 的
`dict[Source, str]` 从本类派生，与它住哪无关。
"""

class Source:
    ...          # 8 个常量逐字节不动

SourceName = Literal[...]   # 逐字节不动
```

**改动** `trace/datastore/trace_event.py`：
**从本文件删掉 `Source` / `SourceName`**（搬走了）。
**改动** `trace/datastore/__init__.py`：`__all__` 去掉 `"Source"`。
**改动** `trace/__init__.py`：`__all__` 去掉 `"Source"` 与 `"TraceEvent"`，
docstring 补一句"`Source`/`TraceEvent` 已搬去 `schemas.harness`"。

### 步骤 5 —— `trace/datastore/trace_event.py` 收缩成词表

旧址**保留文件**（不删），内容收缩成 trace 自己的四样：

```python
"""trace 的词表与落盘版本号。

**`TraceEvent` 与 `Source` 已搬走**（0913）：前者是两个信封的字段类型（跨层
数据形状），后者是项目的生产者词表（trace 零引用）。都去了
`pokemon_agent.schemas.harness.domain`。

**留下的两个东西是 trace 自己的**：
- `EventType`——`store.py` **真的读**它（`event.type == EventType.LIFECYCLE`
  判"这一段收尾了吗"），所以它归 trace。**注意**它与 `TraceKind` 不是同一个
  概念：`TraceKind`（harness 声明"我记哪一笔账"）住 `schemas/harness/domain/`；
  两者的对应关系在 `tools/trace/render.py`——那是桥上的转换。
- `TRACE_SCHEMA_VERSION`——事件形状的版本号，trace 自己的落盘契约。
"""

TRACE_SCHEMA_VERSION = 4     # 逐字节不动
class EventType: ...         # 逐字节不动
EventTypeName = Literal[...] # 逐字节不动
```

**改动** `trace/datastore/__init__.py`：
`__all__ = ["TRACE_SCHEMA_VERSION", "EventType", "_Event"]`，
`from .event import _Event`，`from .trace_event import TRACE_SCHEMA_VERSION, EventType`。

### 步骤 6 —— `store.py` 改 `_Event`

**改动** `pokemon_agent/trace/store.py`：

1. import：`from .datastore import TRACE_SCHEMA_VERSION, EventType, _Event`
2. `append()` 里构造事件的语句（改造前 12 个字段，7 个是项目的事，
   靠 pydantic 默认值静默补）：

```python
# 改造后：trace 只写自己认识的六个
event = _Event(
    event_id=event_id,
    episode_id=episode_id,
    step=step,
    type=type,
    payload=payload or {},
    frame_png=frame_png,
)
```

3. **落盘要写出 `TraceEvent` 的完整形状**（含项目装饰），否则前端/SSE 读到的事件会缺
   字段、`_scan_events` 解析回来也会缺。**这是本方案唯一需要 tool 层参与的地方**——
   在 `LocalTrace.__init__` 加一个**注入的补齐钩子**（缺省 `None`）：

```python
def __init__(
    self,
    run_id: str = "local",
    event_sink: Callable[[Event], None] | None = None,
    decorate: Callable[[Event, str], dict[str, object]] | None = None,
) -> None:
    """...
    `decorate`：把 trace 的 `_Event` 补成项目完整形状的**额外字段**。
        签名 `(event, source) -> dict`，返回要并进落盘 json 的键值。
        **trace 不解释这些键**——它们由项目（tool 层）注入。
        缺省 `None` = 只落 trace 自己的六个字段（独立使用 trace 时的形态）。
    """
```

   落盘处：

```python
raw = event.model_dump()
if self._decorate is not None:
    raw.update(self._decorate(event, source))
_atomic_write_text(
    self._events_dir / f"{self._event_filename(event_id)}.json",
    json.dumps(raw, ensure_ascii=False, default=str),
)
```

   ⚠️ `event.model_dump_json()` 换成 `json.dumps(...)` 后，`TraceEvent.model_config`
   的 base64 约定不再生效——但 `frame_png` 本来就是 base64 的 `str`，
   所以**磁盘格式不变**（验收 ⑥ 逐字节比对旧新 json）。

4. `_scan_events()`：`TraceEvent.model_validate_json(...)` → `_Event.model_validate_json(...)`
   （`extra="allow"` 保证项目装饰字段随行）。
5. `_save_screenshot()` / `_event_filename()`：参数类型 `TraceEvent` → `_Event`；
   顺手把 `_event_filename` 收窄成 `_event_filename(event_id: int) -> str`。
6. **`STORAGE_ROOT` / `project_root` 一行不动**（§0.3 第 1 条）。

### 步骤 7 —— `TracePort` 加读能力

**改动** `pokemon_agent/trace/interface/trace_port.py`：加 `read_events` / `read_event`

```python
from .event import Event


def read_events(self, episode_id: str | None = None) -> list[Event]:
    """读全部事件（按 event_id 升序），可按 episode 切片。

    episode_id：`None` = 不过滤，返回这个 run 的全部事件。
    后置条件：按 event_id 严格升序；无匹配时返回空列表（不抛异常）。
    失败：磁盘读取失败原样抛出（OOM/权限）——本方法不吞错。
    """
    ...

def read_event(self, event_id: int) -> Event | None:
    """按 event_id 读单条。读不到（不存在/残文件）返回 `None`。"""
    ...
```

**改动** `trace/interface/__init__.py`：`__all__ = ["Event", "TracePort"]`。

### 步骤 8 —— `store.py` 实现读方法

```python
def read_events(self, episode_id: str | None = None) -> list[Event]:
    """（契约见 `TracePort.read_events`）全量扫盘、按 event_id 升序、按局切片。

    每次调用重扫 `events/`——trace 不做内存缓存（`RunDataCenter` 的事件槽
    已经是内存缓存，那是项目侧的事，不在这里重复一份状态）。
    """
    events = self._scan_events()
    if episode_id is None:
        return events
    return [e for e in events if e.episode_id == episode_id]

def read_event(self, event_id: int) -> Event | None:
    """（契约见 `TracePort.read_event`）按 id 单条读。

    文件名是 `<run_id>-<event_id:012d>.json`，所以能 O(1) 定位、不扫目录。
    """
    path = self._events_dir / f"{self._event_filename(event_id)}.json"
    if not path.exists():
        return None
    try:
        return _Event.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None      # 残文件是预期内的运行期情况（与 _scan_events 同一取舍）
```

### 步骤 9 —— tool 层补桥

**改动** `tools/interface/ports.py` 的 `TraceToolPort`：加三个方法
`read_events` / `read_event` / `read_screenshot`（`read_screenshot` 的契约见 §2.5）。
docstring 里"**读方法已删**……运维侧读事件流仍直读 `TracePort`/`LocalTrace`，
不进 tool 层"与"**边界不对称**"两段**必须删掉**——本方案正是把读侧收进工具层，
那句话已经作废。

**改动** `tools/trace/__init__.py` 的 `TraceTool`：

```python
def __init__(self, trace: LocalTrace, *, run_id: str = "local") -> None:
    """接好事件流存储。**同时是 `decorate` 钩子的生产者**——见 `_decorate`。"""
    self._trace = trace
    self._run_id = run_id
    trace.bind_decorator(self._decorate)     # 单向下推：tool → trace

def read_events(self, episode_id: str | None = None) -> list[TraceEvent]:
    """读 trace 的 `Event`、补成项目认识的 `TraceEvent`。"""
    return [self._decorate(e) for e in self._trace.read_events(episode_id)]

def read_event(self, event_id: int) -> TraceEvent | None:
    raw = self._trace.read_event(event_id)
    return None if raw is None else self._decorate(raw)

def read_screenshot(self, event_id: int) -> bytes | None:
    return self._trace.read_screenshot(self._run_id, event_id)

@staticmethod
def _decorate(event: Event) -> TraceEvent:
    """trace 的 `Event` → 项目的 `TraceEvent`（**读侧的裸字段 → 业务形状**）。

    从 `event.model_extra` 取回项目装饰字段（`source`/`ts`/`valid`/…）——
    它们是 trace 不认识的，所以由本层负责。**这是本项目第一次从 trace 读事件，
    也是 M1 那条边在读侧的落点。**
    """
    ...
```

**改动** `build.py`：见 §2.6（`TraceTool.build()` + 去掉返回元组里的 `trace`）。

### 步骤 10 —— harness 读点改经 tool

| 文件 | 现状 | 改成 |
|---|---|---|
| `harness/run_data_center.py:35` | `from pokemon_agent.trace import TraceEvent` | `from pokemon_agent.schemas.harness import TraceEvent` |
| `harness/run_data_center.py:74` | `def events(...) -> list[TraceEvent]`（读 `self._events` 内存槽） | **保持**——它读的是自己 `event_sink` 双写的槽，不是 trace。只改 import 来源 |
| `harness/run/nodes/review.py:21` | `from pokemon_agent.trace import TraceEvent` | `from pokemon_agent.schemas.harness import TraceEvent` |
| `harness/run/nodes/review.py:63` | `data_center.events()` | **保持**（同上，内存槽） |
| `harness/run/nodes/plan.py:43` | `from pokemon_agent.trace import EventType, Source` | `from pokemon_agent.schemas.harness import Source`；`EventType` 那半删掉（M3） |
| `harness/run/nodes/plan.py:48,165` | `RUN_TRACE_MASK` | **删**；`data_center.events()` |
| `harness/run/nodes/__init__.py:21,31` | re-export `RUN_TRACE_MASK` | 去掉 |
| `harness/episode/episode_frames.py:19,65` | `read_screenshot(...)` 直调 | `deps.trace.read_screenshot(event_id)` |
| `harness/episode/{close/verify_and_summarize,decide/think_action,gate/judge,press/perceive_after_action}.py` | `from pokemon_agent.trace import Source` | `from pokemon_agent.schemas.harness import Source` |

### 步骤 11 —— 信封与 prompts 的 import

| 文件 | 改动 |
|---|---|
| `schemas/.../FromHarnessToBrainToolPlanOnceReq.py:13` | → `from pokemon_agent.schemas.harness.domain import TraceEvent` |
| 同上 `:33` | `events: list[TraceEvent]` 不变 |
| 同上 docstring | "按 `RUN_TRACE_MASK` 过滤过的" → "该 run 的全量事件流，渲染层自筛" |
| `schemas/.../FromHarnessToReviewerReviewReq.py:8` | → `from pokemon_agent.schemas.harness.domain import TraceEvent` |
| `tools/prompts/run_plan.py:12` | `from pokemon_agent.trace import EventType, TraceEvent` → 拆两行：`from pokemon_agent.schemas.harness import TraceEvent` + `from pokemon_agent.trace import EventType`（**后者合法：tool 层**） |

⚠️ **必须用 `from .domain import TraceEvent` 而不是包出口**——走包出口会触发
`schemas.harness.__init__` 半加载。v1 实测确认这是唯一成环点。

### 步骤 12 —— `tools/trace/render.py` 改一处

```python
- from pokemon_agent.trace import EventType, Source
+ from pokemon_agent.schemas.harness import Source
+ from pokemon_agent.trace import EventType
```

`render.py` **不 import `TraceEvent`**（它只消费 `FromHarnessToTraceToolAppendReq`），
所以除上面这一行外**零改动**。`_LINK_NAME: dict[Source, str]` 照旧。

### 步骤 13 —— `api.py` 删死码 + 改元组

见 §2.6、§2.7。另外 `api.py` 提到 `LocalTrace` 的两处 docstring
（`:26`、`:530`）改成"`RunDataCenter` 的事件槽"。

### 步骤 14 —— `CHANGELOG.md` 追加条目

四段固定格式（改了什么 / 为什么这么改 / 取舍 / 影响面）。

---

## 4. 改动文件总表

| # | 文件 | 动作 | 规模 |
|---|---|---|:---:|
| 1 | `trace/interface/event.py` | **新增** `Event` 协议 | ~50 |
| 2 | `trace/interface/__init__.py` | 加 `Event` | ~5 |
| 3 | `trace/datastore/event.py` | **新增** `_Event`（`extra="allow"`） | ~35 |
| 4 | `trace/datastore/trace_event.py` | 收缩成 `EventType` + 版本号 | 删 ~80 |
| 5 | `trace/datastore/__init__.py` | 改 re-export | ~5 |
| 6 | `trace/__init__.py` | 去掉 `Source`/`TraceEvent` | ~10 |
| 7 | `trace/store.py` | `_Event` 化 + `decorate` 钩子 + 两个读方法 | ~60 |
| 8 | `trace/interface/trace_port.py` | 加 `read_events`/`read_event` | ~40 |
| 9 | `schemas/harness/domain/trace_event.py` | **移入** `TraceEvent` | ~120 |
| 10 | `schemas/harness/domain/source.py` | **移入** `Source`+`SourceName` | ~50 |
| 11 | `schemas/harness/domain/__init__.py` | 加 `Source`/`TraceEvent` | ~5 |
| 12 | `schemas/harness/__init__.py` | 加两行 | ~3 |
| 13 | `schemas/.../FromHarnessToBrainToolPlanOnceReq.py` | 改 import + docstring | ~3 |
| 14 | `schemas/.../FromHarnessToReviewerReviewReq.py` | 改 import | ~1 |
| 15 | `tools/interface/ports.py` | `TraceToolPort` 加 3 方法 + 删过期 docstring | ~35 |
| 16 | `tools/trace/__init__.py` | `build()` + 3 读方法 + `_decorate` | ~60 |
| 17 | `tools/trace/render.py` | 拆 import | ~2 |
| 18 | `tools/prompts/run_plan.py` | 拆 import | ~2 |
| 19 | `build.py` | `TraceTool.build()` + 去掉返回元组里的 `trace` | ~5 |
| 20 | `harness/run_data_center.py` | 改 import | ~1 |
| 21 | `harness/run/nodes/review.py` | 改 import | ~1 |
| 22 | `harness/run/nodes/plan.py` | 改 import + 删 `RUN_TRACE_MASK` | ~6 |
| 23 | `harness/run/nodes/__init__.py` | 去掉 `RUN_TRACE_MASK` re-export | ~3 |
| 24 | `harness/episode/episode_frames.py` | 改走 `deps.trace` | ~2 |
| 25 | `harness/episode/{close,decide,gate,press}/*.py` ×4 | 改 import | ×1 |
| 26 | `api.py` | 删死码 + 3 元组 + docstring | ~10 |
| 27 | `experiment/real_check/check_harness.py` | 解包改 3 元组 | ~1 |
| 28 | `CHANGELOG.md` | 追加条目 | — |

**不动**：`trace/store.py` 的 `project_root`/`STORAGE_ROOT`（§0.3）；
`EventType`/`EventTypeName` 的定义；`tools/trace/render.py` 的 `Source.X`/`EventType.X`
字面量用法；`_LINK_NAME` 的派生方式。

---

## 5. 执行顺序（每步可独立验证）

```
① Event 协议 + _Event 实现（步骤 1、2）          ← 纯新增，零风险
   验证：import 两个新文件；isinstance 检查通过
② TraceEvent + Source 移出（步骤 3、4、5、11）   ← 这一步会短暂破 import
   验证：逐模块独立解释器导入；两个信封能构造
③ store.py `_Event` 化 + 读方法（步骤 6、8）     ← 核心
   验证：落盘 json 与改造前逐字节比对
④ TracePort 加读 + TraceTool 加桥（步骤 7、9）   ← 桥建成
   验证：`deps.trace.read_events()` / `read_screenshot()` 可用
⑤ harness / build / api 改经 tool（步骤 10、12、13）
   验证：§0.1 那条 grep 无输出
⑥ CHANGELOG + 审计文档升级
```

**每步一个 commit**（用户规矩：不用 `git commit` 之外的危险操作；
本方案不含任何 `git reset`/`checkout`）。

---

## 6. 验收标准

```bash
PY="C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe"

# ① 【本方案的主判据】非 tool 引用为零
grep -rn "from pokemon_agent.trace\|import pokemon_agent.trace" pokemon_agent/ --include=*.py \
  | grep -v "^pokemon_agent/tools/"
#    期望：**无输出**
#    另：tools/ 下的命中应恰好 2 处（render.py 的 EventType、prompts/run_plan.py 的 EventType）
#        + 1 处 TracePort（trace/__init__.py:36）+ 1 处 LocalTrace（trace/__init__.py 的 build() 内）

# ② trace 本体对外依赖仍为零（AST 全树，含函数内 import）
#    期望：只有 pokemon_agent.trace.* 自己 + 标准库 + pydantic

# ③ schemas/harness/domain/ 零 trace import（硬约束）
grep -rn "pokemon_agent.trace" pokemon_agent/schemas/harness/domain/
#    期望：无输出

# ④ 逐模块独立解释器导入（唯一抓得到循环导入的方法）
for m in trace schemas.harness schemas.harness.domain tools.trace tools.interface \
         harness build tools memory world brain api; do
  $PY -c "import pokemon_agent.$m" || echo "FAIL: $m"
done
#    期望：**全部通过、0 失败**

# ⑤ Protocol 结构化满足
$PY -c "
from pokemon_agent.trace import Event
from pokemon_agent.schemas.harness import TraceEvent
ev = TraceEvent(event_id=0, run_id='r', episode_id='e', step=0,
                type='lifecycle', source='harness', ts=0.0)
assert isinstance(ev, Event), 'TraceEvent 不满足 Event 协议'
print('协议满足 OK')
"

# ⑥ 落盘格式不变（关键回归）
#    跑一个最小 LocalTrace，比对改造前后 events/*.json 的键集合与值

# ⑦ 行为不变（关键回归）
#    history_lines 的输入从"mask 后"变"全量"，输出必须逐字节相同
```

**⑧ 真实 harness 由用户运行**（按用户规矩，AI 不跑）。

---

## 7. 风险与取舍

| 风险 | 影响 | 缓解 |
|---|---|---|
| **落盘 json 丢字段** | 前端/SSE 读到的事件缺 `source`/`ts`，静默错 | 步骤 6 的 `decorate` 钩子 + 验收 ⑥ 逐字段比对 |
| **`_Event` 的 `extra="allow"` 掩盖拼写错误** | 写错的键被静默收进 `model_extra` | `_Event` 只在 trace 内部用，写入侧是 `decorate`（tool 层控制），风险可控 |
| **信封 import 走包出口 → 成环** | import 时炸 | 验收 ④ 是唯一判据；必须 `from .domain import` |
| **`schemas/harness/domain/` import trace → 成环** | `ImportError`（**v1 已实测复现**） | `TRACE_SCHEMA_VERSION` 本地复制；验收 ③ |
| **`req.events` 由 mask 后变全量** | 信封携带的事件数变多 | 同进程内的列表浅拷贝，不复制对象；`history_lines` 输出不变（验收 ⑦） |
| **`build_real` 返回值少一个元素** | 调用方解包报错 | 只有 2 个调用方（`api.py`、`check_harness.py`），同批改 |
| **改造面较大**（28 个文件） | 回归风险 | 按 §5 分 6 步、每步一个 commit + 独立验证 |

**v1 已验证的技术前提**（在最小骨架里跑通）：

| 验证项 | 结果 |
|---|---|
| `Event` 做成 `@runtime_checkable Protocol`，pydantic 模型结构化满足 | ✅ `isinstance` 为 `True` |
| `_Event` 加 `extra="allow"` 能保留并回写项目装饰字段 | ✅ `model_dump() == 原始 raw` |
| `Event` 作为 `read_events()` 返回类型标注 | ✅ 可用 |
| 信封直接 `from ...domain import TraceEvent` ⇒ 不成环 | ✅ 两方向干净导入 |
| `domain/trace_event.py` import `pokemon_agent.trace` ⇒ 成环 | ❌ 实测 `ImportError` |

**本版新增的实测结论**：

| 验证项 | 结果 |
|---|---|
| `trace/` 全包对 `Source` 的引用 | ✅ 只有 1 处 docstring，**零实现引用** ⇒ 可搬 |
| `trace/store.py` 对 `EventType` 的引用 | ✅ 2 处真消费（`:76`/`:136`）⇒ 留 trace |
| `req.events` 的消费点 | ✅ 只有 `brain_tool.py:440` 一处 |
| `RUN_TRACE_MASK` 的 `ERROR` 半是否被读 | ❌ **从不被读** ⇒ 可删 |

**最大的取舍**：`decorate` 钩子让 `LocalTrace` 多了一个"不清楚对方干什么"的
回调参数。**替代**是让 trace 知道 `TraceEvent`——但那正是要拆掉的东西。
**结论**：钩子是必要的，但要用 docstring 明确"trace 不解释这些键"。

**一个明确不做的事**（留给将来）：trace 现在仍**知道 `EventType.LIFECYCLE`**
（靠它判"这一段收尾了吗"）。要做到**彻底的"trace 零项目词汇"**，得把收尾判定
参数化成 `LocalTrace.__init__(..., episode_end: Callable[[Event], bool])`。
**单独立题、不在本方案内**——理由是：它不影响本方案的任何一条判据
（`EventType` 只有 tool 层引用，合法），且会引入一个行为可见的构造参数。

---

## 8. 一个独立问题（顺手记下）

`pokemon_agent/trace/__init__.py:17` 的 docstring 引用
`scripts/check_graph_phases.py` 的"trace 自持"一项——**该文件不存在**
（`scripts/` 目录当前为空）。

**建议**：把验收 ①②③ 固化成 `scripts/check_trace_self_contained.py`，
让"trace 自持"从一句 docstring 变成可执行的事实。
