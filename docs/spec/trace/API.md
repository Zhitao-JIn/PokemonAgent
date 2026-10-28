# trace —— API 接口文档

> sense_call 已停止产出，旧账仍可读；TraceKind 与解析、渲染映射保持兼容。

> 最后更新：2026-10-22 ｜ 活文档：跟随代码更新，与代码冲突时**以代码为准**
>
> 本文档是 **API 参考**（调什么、怎么调、出错什么样）；
> 模块的边界与全貌（为什么这么设计、谁认识谁）见同目录 [`SPEC.md`](./SPEC.md)；
> 每种账的正文样例见 [`../TRACE_37_accounts_examples.md`](../TRACE_37_accounts_examples.md)；
> `kind` → `type` → 生产位置的**总表**见 [`../DATAFLOW.md`](../DATAFLOW.md) 第四节。

---

## 一、import 什么

消费方**一律**从包根进口，不深到子目录模块文件：

```python
from pokemon_agent.trace import LangfuseTrace, LocalTrace, TracePort
```

包根 `trace/__init__.py` 的 `__all__` 恰好六个名字：

| 名字 | 是什么 | 声明位置 |
|---|---|---|
| `TracePort` | 港口协议（`@runtime_checkable Protocol`），append/read/flush/shutdown | `trace/interface/trace_port.py` |
| `Event` | 形状协议（`@runtime_checkable Protocol`），八个属性 | `trace/interface/event.py` |
| `LocalTrace` | `TracePort` 的本地文件实现 | `trace/store.py` |
| `LangfuseTrace` | `TracePort` 的本机自托管 Langfuse 实现 | `trace/langfuse_trace.py` |
| `new_event_uuid` | 造一个时间递增 uuid（v7 布局）当文件名 | `trace/store.py` |
| `EventType` | 粗类词表的七个字符串常量（**不是枚举**） | `trace/datastore/trace_event.py` |

**不在这里的东西**：`_Event`（`trace/datastore/event.py`，trace 私有实现，**不进任何 `__all__`**）；
`TraceKind`（住 `pokemon_agent.schemas.harness`，是 harness 的账名，不是 trace 的）。

> **谁该调 trace**：只有 tool 层（`pokemon_agent/direct/trace/`）。harness / brain / memory /
> world / schemas / `build.py` 一律不 import 本包，它们经 `TraceToolPort` 说话。
> 显式例外是独立启动入口 `reviewer/__main__.py`（只读 `LocalTrace` 读账，设计侧 2026-10-22 裁决）。
> 这条边界是可执行核对的，见本文第八节（8.1）。

---

## 二、`TracePort` —— 事件读写与生命周期

`trace/interface/trace_port.py`。对外方法包括 `append`、`read_events`、`flush` 和 `shutdown`。

```python
@runtime_checkable
class TracePort(Protocol):
    def append(self, type: str, kind: str,
               meta: dict[str, Any] | None = None, content: Any = None, *,
               started_at: float | None = None,
               ended_at: float | None = None) -> str: ...
    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]: ...
    def flush(self) -> None: ...
    def shutdown(self) -> None: ...
```

**签名里的 `type` / `kind` 是裸 `str`**（0913 降级）：合法值域是**声明方**的事，
trace 不认识——它只保证"按时间记账"。调用方（tool 层）用 `EventType.X` / `TraceKind.X` 的值填。

### 2.1 `append`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | `str` | ✅ | 事件种类。值来自 `EventType` |
| `kind` | `str` | ✅ | 账名。值来自 `TraceKind` |
| `meta` | `dict[str, Any] \| None` | ❌（缺省 `None`→`{}`） | 签名信息，由调用方（tool 层）交齐——**已含 `run_id` / `branch`**；LocalTrace 原样透传，不解释任何键 |
| `content` | `Any` | ❌（缺省 `None`） | 这笔账的本体，任何可 JSON 化的对象 |
| `started_at` | `float \| None` | ❌（缺省 `None`） | 操作**真实开始**时刻；`None` = 落盘层补记账时刻 |
| `ended_at` | `float \| None` | ❌（缺省 `None`） | 操作**结束**时刻；`None` = 落盘层补记账时刻。**排序键的一半** |

**返回**：`str` —— 这个事件的本地 `uuid`。LocalTrace 中它与落盘文件名同值；Langfuse 中它与 observation ID 区分。

**前置条件**：无——`meta` 由调用方（tool 层）在调用时盖好 `run_id` / `branch` 后整份交来，
LocalTrace **不 assert 任何键、只透传**（0927 定案：执行线标识住 tool 层，trace 后端零持有）。

**LocalTrace 后置条件**：

1. 八个字段（`uuid` / `seq` / `kind` / `type` / `started_at` / `ended_at` / `meta` / `content`）已全部落盘；
2. 返回的 uuid 与文件名同值；
3. `seq` 单调递增（进程内全局，`next_seq()` 取号；双后端共享、重启置零、不持久化）；
4. `content` 不可 JSON 序列化 → 抛 `TypeError`，**且不落盘**（序列化在构造事件时就跑完，写盘在其后）。

**Langfuse 后置条件**：append 返回不保证 Observations API 立即可读；`flush()` 只保证 SDK 队列发送，仍接受服务端最终一致性。`read_events()` 失败向上抛出。

**编码约定**：`meta` / `content` 传进去的**是 Python 对象**，trace 负责
`json.dumps(..., ensure_ascii=False)` 序列化成**字符串**落盘；
**序列化只在这一处做**，调用方不要再自己 `json.dumps` 一次（那是双重编码）。

> **同刻 `ended_at` 靠 `seq` 决胜**：`seq` 是**进程内全局**计数器（`trace/seq.py` 的
> `next_seq()`，两个后端共享、重启置零、不持久化）。同一进程内多个 `LocalTrace` 实例写
> 同一落盘根，同刻账仍按真实 append 序排；**跨进程不保序**——各进程各一个计数器，
> 重启后也从零开始。

### 2.2 `read_events`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `meta` | `dict[str, Any] \| None` | ❌（缺省 `None`） | 筛选条件。`None` / `{}` = 不过滤（返回**整个落盘根**）；给了就只返回**每个键都相等**的那批 |

**返回**：`list[Event]`，按 **`(ended_at, seq)` 升序**。

**筛选语义是交集（AND-of-equalities）**：各条件的候选集取交集——**不支持 OR、
不支持大小比较**（与 `MemoryStorePort.filter` 同一条）。键取 `meta` 自己的六键
（`run_id` / `branch` / `source` / `episode_id` / `task_id` / `step`）：

```python
read_events({"run_id": "realcheck-0916-080606"})                         # 整 run
read_events({"run_id": "…", "episode_id": "realcheck-0916-080606-ep1"})  # 某一局
read_events({"source": "act"})                                           # 某个位置发的账
read_events()                                                            # 整个落盘根
```

**落盘不按 run 分层**（0916），所以 `run_id` 是切片的主键——`read_events()`
不带条件时返回的是**整个落盘根**，含别的 run 的事件。

**事件缺某个键时不匹配**——不是"当作空值相等"。所以 `{"run_id": ""}` 捞不到
缺 `run_id` 的残文件。

**后置条件**：严格按 `(ended_at, seq)` 升序；无匹配时返回**空列表**（不抛异常）。

**失败模式**：**磁盘读取失败（权限 / IO）原样抛出**——本方法不吞这一类错。
预期内的才跳过：**残文件 / 旧格式**（`ValidationError`）、**非 UTF-8**（`UnicodeDecodeError`）、
**同名目录**（`is_file()` 为假）与 `.tmp` 中间物——`_scan_events()` 对这几类 `continue`。

**读语义**：

- **每次调用重扫落盘根（只扫第一层的 `*.json`，不递归），不做内存缓存**——需要"盘上有什么"就直接问盘。
- 跳过 `.tmp`（原子写的中间物）。
- 筛选要**解一次 `meta`**——封套上没有 `run_id` / `episode_id` 这些维度；
  **解不动的事件不匹配任何条件**（`_meta_of()` 给空 dict，条件全不成立）。
- 这是**通用读**：不做掩码、不做游标、不打标。

**已下线、现在不存在的读入口**（不要照着老代码调）：
`read_event(event_id)`、`cursor()`、`read_disk_events()`、`void_after()`、`read_screenshot()`。

---

## 三、`Event` —— 一条事件记什么

`trace/interface/event.py`。`Event` 是 `Protocol`，**trace 不持有任何一个具体类**——
它只声明"我记账时需要什么"，任何满足这些属性的对象都能交进来。

| 属性 | 类型 | trace 拿它干什么 |
|---|---|---|
| `uuid` | `str` | 落盘（就是文件名）；扫盘时按它去重 |
| `seq` | `int` | 进程内全局 append 序；同刻 `ended_at` 的决胜键 |
| `kind` | `str` | 落盘（**本类不解释取值**） |
| `type` | `str` | 落盘（同上） |
| `started_at` | `float` | 落盘；操作真实开始时刻（机械账 = 记账时刻） |
| `ended_at` | `float` | 排序（`(ended_at, seq)` 升序）、落盘 |
| `meta` | `str` | 落盘随行；**按交集筛选时读它**（`read_events` 的 `meta` 参数） |
| `content` | `str` | 落盘随行 |

注意 `meta` / `content` 在这份协议里的类型是 **`str`**（已是 JSON 字符串），
而 `append()` 的形参收的是 `Any` / `dict`——**转换发生在 `append` 内部**。

### 三处形状必须逐字段对齐（**没有编译器保护**）

| 处 | 文件 | 角色 |
|---|---|---|
| 协议 | `trace/interface/event.py::Event` | 结构化声明 |
| trace 实现 | `trace/datastore/event.py::_Event` | trace 私有 Pydantic，`extra="allow"`，不进 `__all__` |
| 项目侧 | `schemas/harness/domain/trace_event.py::TraceEvent` | 跨层数据形状（出现在信封里），**结构化满足** `Event`，不继承、不 import trace |

改一处**必须手工同步另外两处**——结构化满足是隐式的，字段对不上时不会报错、只会静默丢字段。
机械保障两处（都在默认测试集里）：`tests/trace/test_trace_event_protocol.py`（协议 ↔ 盘上记录的键）
与 `tests/direct/trace/test_trace_event_alignment.py`（`TraceEvent` 字段集合 == `Event` 属性集合）。

---

## 四、落盘形态

### 4.1 路径

```
<落盘根>/<uuid>.json
```

一条事件**一个 json 文件，全平铺在落盘根下**——**没有 `run_id/` 也没有 `events/`
这两层**（0916 起）。run 的区分靠 `meta.run_id`（见 2.2）。
落盘根由构造参数给，缺省是启动目录下的 `tracelog/`（见第五节）。

### 4.2 八个字段

```json
{
  "uuid": "01a1648a-5bed-77dd-8736-48170fbeb6cb",
  "seq": 3,
  "kind": "advance_step",
  "type": "lifecycle",
  "started_at": 1792688151.5338655,
  "ended_at": 1792688151.5338655,
  "meta": "{\"run_id\": \"my-run\", \"branch\": \"main\", \"source\": \"close_step\", \"episode_id\": \"my-run-ep1\", \"task_id\": \"my-run-ep1-t1\", \"step\": 3}",
  "content": "{\"next_step\": \"4\"}"
}
```

上面是盘上真实的一条（2026-10-22 实测：经 `TraceTool` 落盘后原样贴出；`uuid` / `seq` /
时间戳每次运行都不同）。**注意 `meta` / `content` 是带转义的 JSON 字符串**，读端要
`json.loads` 回来。

| 字段 | 类型 | 谁写 | 说明 |
|---|---|---|---|
| `uuid` | `str` | `store.py`（落盘那一刻） | 文件名同值；`new_event_uuid()` 造 |
| `seq` | `int` | `store.py`（append 时取 `next_seq()`） | 进程内全局单调序号；同刻 `ended_at` 的决胜键 |
| `kind` | `str` | 调用方 | 账名，直接就是 `TraceKind` 的值（**没有翻译表**） |
| `type` | `str` | 调用方 | 粗类，`EventType` 的值 |
| `started_at` | `float` | 调用方交，缺省 `store.py` 补 | 操作真实开始时刻；没交 = 记账时刻 |
| `ended_at` | `float` | 调用方交，缺省 `store.py` 补 | 操作结束时刻；排序键的一半 |
| `meta` | `str` | 调用方交齐四件，tool 层盖 `run_id` / `branch` | JSON 字符串，恰好六键 |
| `content` | `str` | 调用方 | JSON 字符串 |

### 4.3 `meta` 的六个键

| 键 | 谁填 | 说明 |
|---|---|---|
| `run_id` | **`TraceTool.append`**（`direct/trace/__init__.py::_stamp_meta`，盖在**头两个**） | = 本次 run 的标识。**平铺之后它是唯一能回答"这条账属于哪个 run"的字段**，也是切片的主键 |
| `branch` | 同上 | 执行线的分支名（未经恢复为 `main`） |
| `source` | 调用方（harness） | 发这条账的位置：图上节点名，或图外入口名（如 `run_entry.new_run`） |
| `episode_id` | 调用方（harness） | 发在哪一局 |
| `task_id` | 调用方（harness） | 发在哪个任务 |
| `step` | 调用方（harness） | 发在哪一步 |

**上层账的空位放本层 id**：run 级账 `episode_id` / `task_id` 位放 `run_id`、`step` = 已派局数；
episode 级账 `task_id` 位放 `episode_id`。

### 4.4 原子写

`_atomic_write_text()`：先写 `path.with_suffix(".json.tmp")`，再 `os.replace(tmp, path)`。
写完即完整，崩溃最多少一个未 rename 的 `.tmp`——**盘上不会出现半截 JSON**。

### 4.5 时间递增 uuid（`new_event_uuid`）

RFC 9562 的 **v7 布局**，前 48 位是毫秒时间戳：

```
| 48 位毫秒时间戳 | 4 位版本号(7) | 12 位随机 A | 2 位变体(10) | 62 位随机 B |
```

**跨毫秒**生成的 id 按字典序排 ≈ 按时间排；**同一毫秒内**那两段随机，彼此不保序。
用处只有"肉眼和 `ls` 看着大致有序、同目录不撞名"；**排序的真源是 `(ended_at, seq)`**。

为什么不用标准库：`uuid.uuid7()` 要到 Python 3.14 才有（`pyproject.toml` 的
`requires-python = ">=3.11"`），`uuid.uuid1()` 会把网卡 MAC 写进 id。这份实现只用
`time` / `os.urandom` / `uuid.UUID`。

### 4.6 `EventType` 七类

`trace/datastore/trace_event.py`，**字符串常量类不是枚举**；合法值域的类型级表达是 `EventTypeName`（`Literal[...]`）。

| 常量 | 值 | 覆盖的 kind |
|---|---|---|
| `MODEL_CALL` | `model_call` | 九条链共用的调用账 |
| `ERROR` | `error` | `call_failed` / `call_exhausted` / `summary_parse_error` / `checkpoint_error` |
| `LLM_OUTCOME` | `llm_outcome` | `choose_verdict` 与三个 `*_verdict`（与 `MODEL_CALL` 配对） |
| `VIEW` | `view` | `sense_frame`（run / episode / task 内存观测） |
| `ACT` | `act` | `act_call`（key/script 两形，P5 起原 `press_key` 改名；脚本也走 script 形） / `get_action_space` / `check_stall` |
| `MEMORY_IO` | `memory_io` | 六条 `read_*` + 五条 `write_*` |
| `LIFECYCLE` | `lifecycle` | 三层边界账（run / episode / task 各三本）+ `advance_step` + `settle_goal` / `settle_task` + `checkpoint_save` / `checkpoint_restore` + `review_inject` / `review_audit` + `budget_clamped` / `budget_skipped` |

`TraceKind`（51 个成员，`StrEnum`）与 `EventType` **不是一个概念，不能合并**——
`type` 回答"这条记录相对世界 / 模型站在哪个位置"（数量极小、与链路正交），
`kind` 回答"这是哪笔账"。映射关系是"**每个 kind 恰好落一个 type**"，
**由渲染层 `direct/trace/render.py` 给出，trace 自己不持有这张映射**。
逐一对应见 [`../DATAFLOW.md`](../DATAFLOW.md) 第四节「事件总表」。

---

## 五、`LocalTrace` —— 本地文件实现

`trace/store.py`。

```python
class LocalTrace:
    def __init__(self, root: Path | str | None = None) -> None: ...
```

| 参数 | 类型 | 缺省 | 说明 |
|---|---|---|---|
| `root` | `Path \| str \| None` | `None` | **落盘根**（一条事件一个文件那个目录）；`None` = 启动目录下的 `tracelog/`。`str` 也收（构造里 `Path(root)` 归一） |

**构造做什么**：建 `<root>/` **一层**（`parents=True, exist_ok=True`）。
**构造时不扫盘**——`event_id` 计数器与 `id → 文件` 索引已随封套改造下线，落盘只需要目录在；
同刻决胜由封套 `seq` 承担（0928 325），本类不再自己推进时刻。

**缺省落盘根 = `Path.cwd() / "tracelog"`**（0916 起）。trace 是独立第三方模块，
"项目仓库根在哪"不是它该知道的事——曾经的 `Path(__file__)` 回溯三层已删。

**本类不持有 `run_id` / `branch`**（0927 定案）：执行线标识由 tool 层在调用时盖进
`meta`，本类对 `meta` 里的任何键不解释、只透传。**同一落盘根下可以住多个 run**：
事件全平铺在一起，靠 `meta.run_id` 区分（与 `memory/` 同一条规矩——一条记录一个文件，
run_id 在记录里）。所以两个 `LocalTrace(root=同一个目录)` 会写进同一层，彼此不干扰——
`seq` 是进程内全局计数器，两个实例共享同一条序号序列，同刻账仍按 append 序决胜。

### 5.1 落盘根的覆盖链

生产路径逐级递下来，**装配点只递裸字段**：

```
paths.trace（配置文件里的落盘根；build_real 只收 config，型号/路径/服务地址全来自配置）
  └── build_real(config=…)                  pokemon_agent/build.py
        └── TraceTool.build(run_id=…, trace_root=resolve_path(app.paths,"trace"),
                            branch=…, backend=…)
              pokemon_agent/direct/trace/__init__.py
              └── LocalTrace(root=trace_root)  pokemon_agent/trace/store.py
```

测试直接 `LocalTrace(root=tmp_path)`，**不往启动目录写**。

---

## 六、tool 层（harness 认识 trace 的唯一入口）

`pokemon_agent/direct/trace/__init__.py`。harness 面向的是 `TraceToolPort`
（`pokemon_agent/direct/interface/ports.py`），拿到的是 `TraceEvent` 而不是 trace 的 `Event`。

```python
class TraceTool:
    def __init__(self, trace: TracePort, *,
                 run_id: str = "local", branch: str = "main") -> None: ...  # 依赖注入，收任何 TracePort
    @classmethod
    def build(cls, *, run_id: str = "local",
              trace_root: str | Path | None = None,
              branch: str = "main", backend: str = "local") -> TraceTool: ...

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None: ...
    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]: ...
```

**写口只有 `append` 一个**（0916 统一）：调用账也是它——`req.calls` 交**整条
重试链**（`list[ModelCall]`，每次尝试一条），渲染时逐条落成 `*_call` 账、失败的
尝试各自再补一条 `call_failed`。此前的批量口 `append_model_calls` 与它落盘效果
相同，已删。**没发送就没账**：`calls` 为空时调用方干脆
不写这条账（`render.model_call` 对空 `calls` 有 assert）。

`TraceTool.build()` 是**写侧**装配点造 trace 的口（`backend="local"` 时 `new LocalTrace`，
`backend="langfuse"` 时 `new LangfuseTrace`），与 `BrainTool.build()` / `MemoryTool.build()`
同形；读侧的 reviewer 进程另有一个只读 `LocalTrace`（`reviewer/__main__.py`，不写账）。

**tool 层比 trace 多出来的前置条件**（`TraceTool.append` 入口的 assert，全部就地爆炸）：

| assert | 违约说明 |
|---|---|
| `"run_id" not in req.meta` | 执行线标识归**本层**盖（`_stamp_meta`）——调用方带了就是同一件事说两遍 |
| `"branch" not in req.meta` | 同上，分支名也归本层盖 |
| `meta` 带齐 `source` / `episode_id` / `task_id` / `step` | 签名信息由 harness 一次交齐（本层只核不拼） |
| `str(req.meta["source"]).strip()` 非空 | 每笔账都要说清是哪个位置发的 |
| `req.count is None` | 该槽已废：命中条数恒等于 `refs` 的长度 |
| `rendered.kind == req.kind or rendered.type == EventType.ERROR`（`render_request` 出口） | 出口契约：落盘的 kind 只许是请求的那本账，或一条连带产出的错误账 |

`append` 返回 `None` 而不是 uuid：**一笔 req 可能展开成多条事件**，交回一个 id 说不清是哪一个。
要 uuid 就读盘上的文件名。

---

## 七、最小用法示例

三步：造工具 → 记几笔账 → 读回来（2026-10-22 在临时目录实测跑通）。

```python
import json
import tempfile

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.trace import LocalTrace
from pokemon_agent.direct.trace import TraceTool

# 1) 造 tool：落盘根自己给（不传就落进启动目录的 tracelog/）
with tempfile.TemporaryDirectory() as tmp:
    tool = TraceTool(LocalTrace(root=tmp), run_id="my-run")

    # 2) 记一笔账——meta 四件自己交齐，run_id/branch 由 tool 层盖
    tool.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.ADVANCE_STEP,
            meta={"source": "close_step", "episode_id": "my-run-ep1",
                  "task_id": "my-run-ep1-t1", "step": 3},
            next_step=4,
        )
    )

    # 3) 读回来：不筛 / 按 run / 按局（交集）
    events = tool.read_events()                                        # 整个落盘根
    mine = tool.read_events({"run_id": "my-run"})                      # 只要这个 run
    one_episode = tool.read_events({"episode_id": "my-run-ep1"})       # 只要这一局

    event = events[0]
    print(event.uuid, event.kind, event.type)          # 文件名 / 账名 / 粗类
    print(json.loads(event.meta))                       # run_id/branch 已被 tool 层盖上
    print(json.loads(event.content))                    # {'next_step': '4'}
```

实测输出：

```
1 1 1
01a1648a-5b9f-7e37-9492-c1653c9157e6 advance_step lifecycle
{'run_id': 'my-run', 'branch': 'main', 'source': 'close_step', 'episode_id': 'my-run-ep1', 'task_id': 'my-run-ep1-t1', 'step': 3}
{'next_step': '4'}
```

（第一行是 `events` / `mine` / `one_episode` 三个列表的长度；`uuid` 每次运行都不同。）

直接调 `TracePort`（不经 tool 层，只在自己写测试 / 换实现时用）：

```python
store = LocalTrace(root=tmp)
uuid = store.append(
    "lifecycle",
    "advance_step",
    {"run_id": "my-run", "branch": "main", "source": "s",
     "episode_id": "e", "task_id": "e", "step": 0},
    {"next_step": "1"},
)
print(uuid, [(e.uuid, e.seq) for e in store.read_events()])
```

实测输出：

```
01a1648a-5bda-7949-b0b3-15e8149dd11a [('01a1648a-5bda-7949-b0b3-15e8149dd11a', 2)]
```

（`seq` 是进程内全局计数器——同一次进程里先前的 append 已取过 1，所以这里是 2。）

**读回来的编码约定**（渲染层定的跨模块契约）：标量一律 `str()`、布尔一律小写
`"true"` / `"false"`；本来就是结构化数据的那几处（`facts` / `sequence` / `verdicts` /
四本写账的正文）**直接放对象，不再 `json.dumps` 一次**。
所以上面 `content` 里是 `{"next_step": "4"}` 而不是 `{"next_step": 4}`。

---

## 八、怎么核

### 8.1 边界自持（静态，不跑模拟器）

```bash
python scripts/check_trace_self_contained.py
```

退出码 `0` = 全过。只读 import 语句（AST），**不看 docstring 散文**——
注释里提到 `pokemon_agent.trace` 不是依赖边。

| 项 | 名称 | 查什么 |
|---|---|---|
| A | trace 出边为零（可整体拷走） | `trace/` 包内没有任何文件 import `pokemon_agent` 的其余部分 |
| B | 入口只在 `direct/`（`reviewer/__main__.py` 例外） | `trace/` 与 tool 层门面 `direct/` 之外的文件不 import `pokemon_agent.trace`。显式例外只有 `reviewer/__main__.py`——独立启动入口，自带只读 `LocalTrace` 读账、不经 tool 层（设计侧 2026-10-22 裁决）。实测脚本退出码 0，A / B / C 三项全过 |
| C | `schemas/harness/domain` 不 import trace | ⚠ **不是防环**——trace 出边为零（A），任何 `X → trace` 的边都构不成回环，这里 import 它也不炸（0916 实测四种加载顺序全不炸）。守的是**分层方向**：契约层不反向依赖实现包 |

### 8.2 落盘契约（单元测试）

```bash
pytest tests/trace tests/direct/trace
```

139 条（2026-10-22 `--collect-only` 实测；其中 `tests/trace/langfuse/` 39 条，
注入 fake client、全程零联网，不需要真起 Langfuse 服务）。覆盖：

- **契约与形状**：`TracePort` 契约 14 条（`test_trace_port_contract.py`，换实现同一批断言）、
  事件协议与词表 3 条（`test_trace_event_protocol.py`，协议 ↔ 盘上记录 ↔ `EventType`）、
  `TraceEvent` 与 `Event` 字段集合机械对齐 1 条（`test_trace_event_alignment.py`）、
  包边界 3 条（`test_trace_package_boundary.py`，出边为零 / 依赖白名单 / 出口名字固定）；
- **本地落盘**：`LocalTrace.append` 落盘形状 12 条（一事件一文件、八字段、JSON 字符串、
  双时刻缺省）、`read_events` 读语义 4 条（同一落盘根、按 run 切片、只读不改盘）、
  坏文件容忍 8 条（残文件、旧格式、`.tmp`、非 dict 的 `meta`、非 UTF-8、同名目录、
  读取失败原样抛出）、落盘根 4 条（缺省位置、`str` 与 `Path` 同等对待、目录自动创建、
  跨实例可见）、`new_event_uuid` 4 条（v7 布局、跨毫秒字典序、同毫秒不撞名）；
- **序号**：进程内 `next_seq` 与"同刻按 append 序决胜"4 条（`test_trace_append_sequence.py`）、
  同刻事件跨后端实例仍按进程内 append 序 2 条（`test_trace_seq.py`）；
- **tool 门面**：`TraceTool` 契约 7 条（签名校验、执行线盖戳、失败尝试独立成账、
  工厂转发落盘根）、`build` 后端选择 9 条、正文形状 13 条、act_call 两形 2 条、
  读侧解析层 2 条、分支血缘读账 2 条、布尔字面量 2 条、调用账与错误账落盘读回 3 条、
  run 三本账真实渲染 1 条。

**不连网、不碰模拟器、不调模型、不往仓库的 `tracelog/` 写。**

### 8.3 真机产物核对

该核对脚本（`experiment.real_check.check_trace`）**已不在仓库**（`experiment/` 下现仅剩
`paused_window_probe.py`）。要核对真机产物，用 8.2 的测试口径自己写：扫落盘根 →
`TraceTool.read_events()` 或 `LocalTrace.read_events()` 读回 → 逐条查八字段齐、
`meta` 六键、`json.loads` 可还原。本文不再给出该脚本的命令与输出格式。

---

## 九、约束与已知缺口

- **两份八字段形状靠人工同步**：`_Event` 与 `TraceEvent` 之间没有共享基类、没有编译器保护，
  改一处必须同步另一处。机械保障两处（都在默认测试集里）：
  `tests/trace/test_trace_event_protocol.py`（协议 ↔ 盘上记录的键）与
  `tests/direct/trace/test_trace_event_alignment.py`（`TraceEvent` 字段集合 == `Event` 属性集合）。
- **旧格式数据没有迁移路径**（两种都不可见）：① 封套改造之前的老 json 缺 `seq` / `ended_at`
  等必填字段（`_Event` 的必填项是 `uuid`/`seq`/`kind`/`type`/`started_at`/`ended_at`），
  `_scan_events` 解析当场失败、跳过；② 分层时代（`<run_id>/events/`）的文件根本不在
  扫描范围内——只扫第一层、不递归。两种都是"被静默丢弃"而不是"被读成空值"，
  没有迁移 / 报告工具。
- **`seq` 是进程内计数器，跨进程不保序**：`next_seq()` 每个进程一个、重启置零，
  两个进程同时写一个落盘根（或重启后接着写）时，同刻账的决胜次序没有保证。
- **平铺之后没有目录可认 run**：`read_events()` 不带条件返回的是**整个落盘根**
  （含别的 run 的事件），按 run 取账必须自己传 `{"run_id": …}`。
- **trace 自己不校验 `kind` / `type` 的值域**：`TracePort.append` 收的是裸 `str`，
  传错值不会报错，会原样落盘。值域的守门人在 tool 层两步：
  `FromHarnessToTraceToolAppendReq.kind` 的字段类型是 `TraceKind`（Pydantic 在构造时就拦），
  过了那关之后由 `_RENDERERS` 分派（未登记的 kind 直接 `KeyError`）。
