# trace —— API 接口文档

> 最后更新：2026-09-16 ｜ 活文档：跟随代码更新，与代码冲突时**以代码为准**
>
> 本文档是 **API 参考**（调什么、怎么调、出错什么样）；
> 模块的边界与全貌（为什么这么设计、谁认识谁）见同目录 [`SPEC.md`](./SPEC.md)；
> 每种账的正文样例见 [`../TRACE_37_accounts_examples.md`](../TRACE_37_accounts_examples.md)；
> `kind` → `type` → 生产位置的**总表**见 [`../DATAFLOW.md`](../DATAFLOW.md) 第四节。

---

## 一、import 什么

消费方**一律**从包根进口，不深到子目录模块文件：

```python
from pokemon_agent.trace import LocalTrace, TracePort   # 常用两个
```

包根 `trace/__init__.py` 的 `__all__` 恰好五个名字：

| 名字 | 是什么 | 声明位置 |
|---|---|---|
| `TracePort` | 港口协议（`@runtime_checkable Protocol`），两个方法 | `trace/interface/trace_port.py` |
| `Event` | 形状协议（`@runtime_checkable Protocol`），六个属性 | `trace/interface/event.py` |
| `LocalTrace` | `TracePort` 的唯一实现（文件落盘） | `trace/store.py` |
| `new_event_uuid` | 造一个时间递增 uuid（v7 布局）当文件名 | `trace/store.py` |
| `EventType` | 粗类词表的七个字符串常量（**不是枚举**） | `trace/datastore/trace_event.py` |

**不在这里的东西**：`_Event`（`trace/datastore/event.py`，trace 私有实现，**不进任何 `__all__`**）；
`TraceKind`（住 `pokemon_agent.schemas.harness`，是 harness 的账名，不是 trace 的）。

> **谁该调 trace**：只有 tool 层（`pokemon_agent/tools/trace/`）。harness / brain / memory /
> world / schemas / `build.py` 一律不 import 本包，它们经 `TraceToolPort` 说话。
> 这条边界是可执行核对的，见本文第六节。

---

## 二、`TracePort` —— 两个方法

`trace/interface/trace_port.py`。**整个模块的对外能力就是这两个方法。**

```python
@runtime_checkable
class TracePort(Protocol):
    def append(self, type: str, kind: str,
               meta: dict[str, Any] | None = None, content: Any = None) -> str: ...
    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]: ...
```

**签名里的 `type` / `kind` 是裸 `str`**（0913 降级）：合法值域是**声明方**的事，
trace 不认识——它只保证"按时间记账"。调用方（tool 层）用 `EventType.X` / `TraceKind.X` 的值填。

### 2.1 `append`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | `str` | ✅ | 事件种类。值来自 `EventType` |
| `kind` | `str` | ✅ | 账名。值来自 `TraceKind` |
| `meta` | `dict[str, Any] \| None` | ❌（缺省 `None`→`{}`） | 签名信息，**不带 `run_id`** |
| `content` | `Any` | ❌（缺省 `None`） | 这笔账的本体，任何可 JSON 化的对象 |

**返回**：`str` —— 这个事件的 `uuid`，**与落盘文件名同值**。

**前置条件（实现方用 assert 执行）**：`meta` 不带 `run_id` 键
（`store._stamp_run_id` 第一条就是 `assert "run_id" not in meta`）。那个键归落盘这一层盖，
调用方带了就是"同一件事说两遍"。

**后置条件**：

1. 六个字段（`uuid` / `kind` / `type` / `ts` / `meta` / `content`）已全部落盘；
2. 返回的 uuid 与文件名同值；
3. **`ts` 严格递增**（本实例内）。墙上时钟分辨率有限，撞刻时人为推进 1µs：
   `if now <= self._last_ts: now = self._last_ts + 1e-6`——读侧"按 `(ts, uuid)` 排序 = 按执行顺序排列"
   这条不变式才真正成立。

**编码约定**：`meta` / `content` 传进去的**是 Python 对象**，trace 负责
`json.dumps(..., ensure_ascii=False)` 序列化成**字符串**落盘；
**序列化只在这一处做**，调用方不要再自己 `json.dumps` 一次（那是双重编码）。

> **⚠ 前提：单实例、单线程顺序调用。** `_last_ts` 是**本实例**的序列基线、不落盘，
> 靠"trace 实例全图共享 + 图是同步 invoke"成立。多实例并发写同一个落盘根**不保序**。

### 2.2 `read_events`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `meta` | `dict[str, Any] \| None` | ❌（缺省 `None`） | 筛选条件。`None` / `{}` = 不过滤（返回**整个落盘根**）；给了就只返回**每个键都相等**的那批 |

**返回**：`list[Event]`，按 **`(ts, uuid)` 升序**。

**筛选语义是交集（AND-of-equalities）**：各条件的候选集取交集——**不支持 OR、
不支持大小比较**（与 `MemoryStorePort.filter` 同一条）。键取 `meta` 自己那四个：

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

**后置条件**：严格按 `(ts, uuid)` 升序；无匹配时返回**空列表**（不抛异常）。

**失败模式**：**磁盘读取失败（权限 / IO）原样抛出**——本方法不吞这一类错。
但**单条文件解析失败不抛**：那是残文件 / 旧格式，属预期内的运行期情况，
`_scan_events()` 静默 `continue`。

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
| `ts` | `float` | 排序（`(ts, uuid)` 升序）、落盘 |
| `kind` | `str` | 落盘（**本类不解释取值**） |
| `type` | `str` | 落盘（同上） |
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
`tests/test_trace_store.py::test_event_has_exactly_the_six_contract_fields` 是这件事唯一的机械保障。

---

## 四、落盘形态

### 4.1 路径

```
<落盘根>/<uuid>.json
```

一条事件**一个 json 文件，全平铺在落盘根下**——**没有 `run_id/` 也没有 `events/`
这两层**（0916 起）。run 的区分靠 `meta.run_id`（见 2.2）。
落盘根由构造参数给，缺省是启动目录下的 `tracelog/`（见第五节）。

### 4.2 六个字段

```json
{
  "uuid": "01a0a698-5498-7bb6-addd-8008e1ec52e3",
  "kind": "run_start",
  "type": "lifecycle",
  "ts": 1789501396.1209698,
  "meta": "{\"run_id\": \"realcheck-0915-214315\", \"source\": \"run_entry.new_run\", \"episode_id\": \"realcheck-0915-214315\", \"step\": 0}",
  "content": "{\"goals\": [...], \"success_criteria\": [...]}"
}
```

上面是盘上真实的 `run_start`（取自 0916 平铺**之前**的产物
`trace_data/realcheck-0915-214315/events/`——该 run 已归档到
`_to_delete/trace_data_legacy_0916/`，`content` 中间省略）——
**字段与现在逐字相同，只有路径两层没了**：平铺之后同一个文件直接躺在落盘根下。
**注意 `meta` / `content` 是带转义的 JSON 字符串**，读端要 `json.loads` 回来。

| 字段 | 类型 | 谁写 | 说明 |
|---|---|---|---|
| `uuid` | `str` | `store.py`（落盘那一刻） | 文件名同值；`new_event_uuid()` 造 |
| `ts` | `float` | `store.py`（写入那一刻） | Unix 秒；排序键 |
| `kind` | `str` | 调用方 | 账名，直接就是 `TraceKind` 的值（**没有翻译表**） |
| `type` | `str` | 调用方 | 粗类，`EventType` 的值 |
| `meta` | `str` | 调用方给三件，落盘层盖 `run_id` | JSON 字符串，恰好四键 |
| `content` | `str` | 调用方 | JSON 字符串 |

### 4.3 `meta` 的四个键

| 键 | 谁填 | 说明 |
|---|---|---|
| `run_id` | **`store._stamp_run_id`**，盖在**头一个** | = 本实例的标识（构造时给的 `run_id`）。**平铺之后它是唯一能回答"这条账属于哪个 run"的字段**，也是切片的主键 |
| `source` | 调用方 | 发这条账的位置：图上节点名，或图外入口名（如 `run_entry.new_run`） |
| `episode_id` | 调用方 | 发在哪一局 |
| `step` | 调用方 | 发在哪一步 |

**run 级账沿用项目约定**：`episode_id` 位放 `run_id`、`step` 恒 `0`。

### 4.4 原子写

`_atomic_write_text()`：先写 `path.with_suffix(".json.tmp")`，再 `os.replace(tmp, path)`。
写完即完整，崩溃最多少一个未 rename 的 `.tmp`——**盘上不会出现半截 JSON**。

### 4.5 时间递增 uuid（`new_event_uuid`）

RFC 9562 的 **v7 布局**，前 48 位是毫秒时间戳：

```
| 48 位毫秒时间戳 | 4 位版本号(7) | 12 位随机 A | 2 位变体(10) | 62 位随机 B |
```

**跨毫秒**生成的 id 按字典序排 ≈ 按时间排；**同一毫秒内**那两段随机，彼此不保序。
用处只有"肉眼和 `ls` 看着大致有序、同目录不撞名"；**排序的真源是 `(ts, uuid)`**。

为什么不用标准库：`uuid.uuid7()` 要到 Python 3.14 才有（本项目跑 3.12），
`uuid.uuid1()` 会把网卡 MAC 写进 id。这份实现只用 `time` / `os.urandom` / `uuid.UUID`。

### 4.6 `EventType` 七类

`trace/datastore/trace_event.py`，**字符串常量类不是枚举**；合法值域的类型级表达是 `EventTypeName`（`Literal[...]`）。

| 常量 | 值 | 覆盖的 kind |
|---|---|---|
| `MODEL_CALL` | `model_call` | 七条链共用的调用账 |
| `ERROR` | `error` | `call_failed` / `call_exhausted` / `summary_parse_error` |
| `LLM_OUTCOME` | `llm_outcome` | `choose_verdict` 与三个 `*_verdict`（与 `MODEL_CALL` 配对） |
| `VIEW` | `view` | `sense_frame`（episode 完整档 / task RAM 档） |
| `ACT` | `act` | `press_key` / `get_action_space` / `check_stall` |
| `MEMORY_IO` | `memory_io` | 六条 `read_*` + 三条 `write_*` |
| `LIFECYCLE` | `lifecycle` | run / episode 边界账 + `advance_step` |

`TraceKind`（35 个成员，`StrEnum`）与 `EventType` **不是一个概念，不能合并**——
`type` 回答"这条记录相对世界 / 模型站在哪个位置"（数量极小、与链路正交），
`kind` 回答"这是哪笔账"。映射关系是"**每个 kind 恰好落一个 type**"，
**由渲染层 `tools/trace/render.py` 给出，trace 自己不持有这张映射**。
逐一对应见 [`../DATAFLOW.md`](../DATAFLOW.md) 第四节「事件总表」。

---

## 五、`LocalTrace` —— 唯一实现

`trace/store.py`。

```python
class LocalTrace:
    def __init__(self, run_id: str = "local", root: Path | None = None) -> None: ...
```

| 参数 | 类型 | 缺省 | 说明 |
|---|---|---|---|
| `run_id` | `str` | `"local"` | 本实例的标识，**只用于盖进 `meta.run_id`，不参与路径** |
| `root` | `Path \| None` | `None` | **落盘根**（一条事件一个文件那个目录）；`None` = 启动目录下的 `tracelog/`。`str` 也收 |

**构造做什么**：建 `<root>/` **一层**（`parents=True, exist_ok=True`）。
**构造时不扫盘**——`event_id` 计数器与 `id → 文件` 索引已随封套改造下线，落盘只需要目录在。

**缺省落盘根 = `Path.cwd() / "tracelog"`**（0916 起）。trace 是独立第三方模块，
"项目仓库根在哪"不是它该知道的事——曾经的 `Path(__file__)` 回溯三层已删。

**同一落盘根下可以住多个 run**：事件全平铺在一起，靠 `meta.run_id` 区分
（与 `memory/` 同一条规矩——一条记录一个文件，run_id 在记录里）。
所以两个 `LocalTrace(root=同一个目录, run_id=不同)` 会写进同一层，彼此不干扰。

### 5.1 落盘根的覆盖链

生产路径逐级递下来，**装配点只递裸字段**：

```
--trace-root PATH（起跑脚本）
  └── build_real(trace_root=…)              pokemon_agent/build.py
        └── TraceTool.build(trace_root=…)   pokemon_agent/tools/trace/__init__.py
              └── LocalTrace(root=…)        pokemon_agent/trace/store.py
```

测试直接 `LocalTrace(run_id=…, root=tmp_path)`，**不往启动目录写**。

---

## 六、tool 层（harness 认识 trace 的唯一入口）

`pokemon_agent/tools/trace/__init__.py`。harness 面向的是 `TraceToolPort`
（`pokemon_agent/tools/interface/ports.py`），拿到的是 `TraceEvent` 而不是 trace 的 `Event`。

```python
class TraceTool:
    def __init__(self, trace: TracePort) -> None: ...          # 依赖注入，收任何 TracePort
    @classmethod
    def build(cls, *, run_id: str = "local",
              trace_root: str | Path | None = None) -> TraceTool: ...

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None: ...
    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]: ...
```

**写口只有 `append` 一个**（0916 统一）：调用账也是它——`req.calls` 交**整条
重试链**（`list[ModelCall]`，每次尝试一条），渲染时逐条落成 `*_call` 账、失败的
尝试各自再补一条 `call_failed`。此前的批量口 `append_model_calls` 与它落盘效果
相同，已删。**没发送就没账**：`calls` 为空（如 `ram_only` 感知）时调用方干脆
不写这条账（`render.model_call` 对空 `calls` 有 assert）。

`TraceTool.build()` 是**全项目唯一 `new LocalTrace` 的地方**，
与 `BrainTool.build()` / `MemoryTool.build()` / `build_vision_provider()` 同形。

**tool 层比 trace 多出来的前置条件**（`TraceTool.append` 入口的 assert，全部就地爆炸）：

| assert | 违约说明 |
|---|---|
| `"run_id" not in req.meta` | 那个键归落盘这一层盖 |
| `meta` 带齐 `source` / `episode_id` / `step` | 签名信息由 harness 一次交齐 |
| `str(req.meta["source"]).strip()` 非空 | 每笔账都要说清是哪个位置发的 |
| `req.count is None` | 该槽已废：命中条数恒等于 `refs` 的长度 |
| `rendered.kind == req.kind or rendered.type == EventType.ERROR` | 出口契约：落盘的 kind 只许是请求的那本账，或一条连带产出的错误账 |

`append` 返回 `None` 而不是 uuid：**一笔 req 可能展开成多条事件**，交回一个 id 说不清是哪一个。
要 uuid 就读盘上的文件名。

---

## 七、最小用法示例

照 `tests/test_trace_store.py` 的三步：造工具 → 记几笔账 → 读回来。

```python
import json

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.trace import LocalTrace
from pokemon_agent.tools.trace import TraceTool

# 1) 造 tool：落盘根自己给（不传就落进启动目录的 tracelog/）
tool = TraceTool(LocalTrace(run_id="my-run", root="/tmp/trace_root"))

# 2) 记一笔账——meta 三件自己交齐，run_id 不要带
tool.append(
    FromHarnessToTraceToolAppendReq(
        kind=TraceKind.ADVANCE_STEP,
        meta={"source": "close_step", "episode_id": "my-run-ep1", "step": 3},
        next_step=4,
    )
)

# 3) 读回来：不筛 / 按 run / 按局（交集）
events = tool.read_events()                                        # 整个落盘根
mine = tool.read_events({"run_id": "my-run"})                      # 只要这个 run
one_episode = tool.read_events({"episode_id": "my-run-ep1"})       # 只要这一局

event = events[0]
print(event.uuid, event.kind, event.type)          # 文件名 / 账名 / 粗类
print(json.loads(event.meta))                       # run_id 已被 store 盖上
print(json.loads(event.content))                    # {'next_step': '4'}
```

直接调 `TracePort`（不经 tool 层，只在自己写测试 / 换实现时用）：

```python
store = LocalTrace(run_id="my-run", root="/tmp/trace_root")
uuid = store.append("lifecycle", "advance_step",
                    {"source": "s", "episode_id": "e", "step": 0}, {"next_step": "1"})
print(uuid, [e.uuid for e in store.read_events()])
```

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
| B | 入口只在 `tools/` | `trace/` 与 `tools/` 之外的文件不许 import `pokemon_agent.trace` |
| C | `schemas/harness/domain` 不 import trace | ⚠ **不是防环**——trace 出边为零（A），任何 `X → trace` 的边都构不成回环，这里 import 它也不炸（0916 实测四种加载顺序全不炸）。守的是**分层方向**：契约层不反向依赖实现包 |

### 8.2 落盘契约（单元测试）

```bash
pytest tests/test_trace_store.py
```

16 条（`grep -c '^def test_'` 口径），覆盖：一条事件一个文件 / 文件名是 v7 uuid 且
住在封套上 / 排序认 `(ts, uuid)` / 恰好六字段 / `meta`·`content` 是 JSON 字符串 /
`run_id` 被盖上 / `meta` 是 harness 的签名且**逐字转发** /
按 `meta` 切片（走内容不走封套）/ 交集是 AND-of-equalities / 缺键不匹配 /
两个 run 共用一层平铺目录且 `run_id` 是切片主键 /
失败尝试各成一条 `call_failed` / 四个前置违约各炸一次（缺键、空 `source`、
调用方带 `run_id`、带 `count`）/ 缺省根是启动目录下的 `tracelog/` /
工厂转发 `trace_root`。
**不连网、不碰模拟器、不调模型、不往仓库的 `tracelog/` 写。**

### 8.3 真机产物核对（维度 2）

```bash
python -m experiment.real_check.check_trace --trace-root <落盘根>
```

前置条件：先跑 `check_harness` 生成 trace 产物。它从 `resolve_run(trace_root)`
拿到 run_id —— 优先读 `<落盘根>/.last_realcheck.json` 这个指针，
指针缺失或悬空（那个 run 在盘上一个事件都没有）时**回退扫描**：把落盘根下
全部事件按 `meta.run_id` 分组，只认 `realcheck-` / `restorecheck-` 开头的那几组，
按 `_recency()` = `(最大 ts, 最大 uuid)` 取最新的一组——**平铺之后"哪个 run
最新"只能从事件内容里推**，没有目录名和 mtime 可认了。兜底位换来的是**确定**
不是"更准"（`time.time()` 步长粗到会让背靠背的两个 run 共用同一个 `ts`，真打平时
赢家任意但固定）。然后查四件事：

1. 每条事件**恰好**六字段、且 `meta` / `content` 都能 `json.loads`；
2. **落盘根下没有读不动的残文件**（事件文件 = 第一层非点开头的 `*.json`，
   `.last_realcheck.json` 不算），且本 run 每条事件的 `uuid` 在盘上都有同名文件、无重号；
3. 骨架 kind 齐全：`run_start`、{`run_end` / `run_error`} 有一个、
   `episode_start`、{`episode_end` / `episode_error`} 有一个；
4. 至少一条 `type=model_call`。

通过时打印 `PASS trace: N 条事件、封套六字段齐、无残文件，骨架 kind 齐全，model_call M 条`。

用到的读法（`experiment/real_check/common.py`，与写方共用一份）：
`load_events(run_id, trace_root=None)` 扫落盘根、按 `meta.run_id` 过滤、跳过解析
失败的文件、按 `(float(ts), str(uuid))` 排序——**与 `store._scan_events` 同一套判据**；
`resolve_run(trace_root=None)` 定位"最近一次真实 run"（指针 → 回退扫描）。

---

## 九、约束与已知缺口

- **两份六字段形状靠人工同步**：`_Event` 与 `TraceEvent` 之间没有共享基类、没有编译器保护，
  改一处必须同步另一处。唯一机械保障是 `tests/test_trace_store.py`。
- **旧格式数据没有迁移路径**（两种都不可见）：① 封套改造之前的老 json 缺 `uuid` / `ts`，
  `_scan_events` 解析当场失败、跳过；② 分层时代（`<run_id>/events/`）的文件根本不在
  扫描范围内——只扫第一层、不递归。两种都是"被静默丢弃"而不是"被读成空值"，
  没有迁移 / 报告工具。
- **`ts` 严格递增依赖单实例、单线程顺序调用**：`_last_ts` 不落盘，
  多实例并发写同一个落盘根不保序。
- **平铺之后没有目录可认 run**：`read_events()` 不带条件返回的是**整个落盘根**
  （含别的 run 的事件），按 run 取账必须自己传 `{"run_id": …}`。核对脚本的
  `resolve_run` 也因此改成从事件内容推"哪个 run 最新"。
- **trace 自己不校验 `kind` / `type` 的值域**：`TracePort.append` 收的是裸 `str`，
  传错值不会报错，会原样落盘。值域的守门人在 tool 层两步：
  `FromHarnessToTraceToolAppendReq.kind` 的字段类型是 `TraceKind`（Pydantic 在构造时就拦），
  过了那关之后由 `_RENDERERS` 分派（未登记的 kind 直接 `KeyError`）。
