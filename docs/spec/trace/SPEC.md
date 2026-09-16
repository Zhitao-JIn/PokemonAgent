# trace —— 模块规格

> 最后更新：2026-09-16 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/trace/` 是一个**独立的第三方模块**：事件流的落盘实现 + 它自己的港口协议 + 形状协议 + 粗类词表。项目侧把它当"拷走即可复用"的成品对待。

- **只保证一件事**：按时间记账。`type` / `kind` / `meta` / `content` 的**合法值域是声明方的事，trace 不认识**——所以 `TracePort.append()` 的前两个参数是裸 `str`。
- **`meta` / `content` 是不透明载荷**：trace 只负责序列化成 JSON 字符串落盘、读回时原样交还，**不解释里面装了什么**。
- **零出边**：包内任何文件不 import `pokemon_agent` 的其余部分（可执行核对见 `scripts/check_trace_self_contained.py` 的 A 项）。
- **入边只在 tool 层**：其余各层（`brain` / `harness` / `memory` / `world` / `schemas` / `vision` 与装配点 `build.py`）一律不 import 它——harness 只经 `HarnessDeps.trace`（`TraceToolPort`）说话（B 项）。
- 统一出口 `trace/__init__.py` 只 re-export 五个名字：`Event`、`EventType`、`LocalTrace`、`TracePort`、`new_event_uuid`。消费方写 `from pokemon_agent.trace import LocalTrace, TracePort`。

## 二、目录结构

```
trace/
├── __init__.py              统一出口（上面五个名字）
├── store.py                 TracePort 的实现 LocalTrace + 缺省落盘根 + new_event_uuid
├── interface/
│   ├── __init__.py          出口：Event / TracePort
│   ├── event.py             Event（形状协议，六属性）
│   └── trace_port.py        TracePort（runtime_checkable Protocol，两方法）
└── datastore/
    ├── __init__.py          出口：EventType
    ├── event.py             _Event（trace 私有的具体实现，不进 __all__）
    └── trace_event.py       EventType（七个字符串常量）+ EventTypeName（Literal）
```

`_Event` 只服务 `store.py`（它 `from .datastore.event import _Event`），**不进任何 `__all__`**；外部一律通过 `Event` 协议说话。

## 三、TracePort 契约

`TracePort`（`trace/interface/trace_port.py`，`@runtime_checkable Protocol`）只有两个方法，签名里全是不带值域的裸类型。

| 方法 | 签名 | 承诺 |
|---|---|---|
| `append` | `(type: str, kind: str, meta: dict[str, Any] \| None = None, content: Any = None) -> str` | 追加一条事件，返回它的 `uuid`（= 文件名） |
| `read_events` | `(meta: dict[str, Any] \| None = None) -> list[Event]` | 读已落盘的全部事件，按 `(ts, uuid)` 升序，可按 `meta` 做交集筛选 |

- `append` **前置条件**：`meta` 不带 `run_id` 键——`store._stamp_run_id` 用 assert 执行这条契约。**后置条件**：六个字段全部落盘；返回的 uuid 与文件名同值。
- `read_events` **筛选语义**：`None` / 空 dict = 整个落盘根；给了就只返回**每个键都相等**的那批——AND-of-equalities，与 `MemoryStorePort.filter` 同一条（不支持 OR、不支持大小比较）。键取 `run_id` / `source` / `episode_id` / `step`；事件缺某个键时**不匹配**（不是当作空值相等）。
- `read_events` **后置条件**：按 `(ts, uuid)` 严格升序；无匹配返回空列表（不抛异常）。磁盘读取失败（权限 / IO）**原样抛出**——本方法不吞这一类错。
- 读能力只剩这一条通用读方法：不做掩码、不做游标、不打标，只回答"盘上有什么"。
- 已下线的入口（现在不存在）：`read_event(event_id)`——画面真源搬到 `memory/step_memory/` 之后没有读者；`cursor()` / `read_disk_events()` / `void_after()`——随 checkpoint 恢复链删；`read_screenshot`——随截图副本删。
- 实现 `LocalTrace(run_id: str = "local", root: Path | None = None)`：`root` 是**落盘根**
  （一条事件一个文件那个目录），缺省为**进程启动目录**下的 `tracelog/`（`Path.cwd()`，0916 起）；
  `run_id` **只用于盖进 `meta`，不参与路径**。生产路径的覆盖链：
  `--trace-root`（起跑脚本）→ `build_real(trace_root=…)` → `TraceTool.build(trace_root=…)` → 这里；
  测试直接传 `tmp_path`。

## 四、事件形状

一条事件**六个字段，一个都不多**。三处形状必须逐字段对齐（**没有编译器保护**）：

| 处 | 文件 | 角色 |
|---|---|---|
| 协议 | `trace/interface/event.py::Event` | 结构化声明：trace 记账真正需要的六样 |
| trace 实现 | `trace/datastore/event.py::_Event` | trace 私有 Pydantic 实现，`model_config = ConfigDict(extra="allow")` |
| 项目侧 | `schemas/harness/domain/trace_event.py::TraceEvent` | 跨层数据形状（出现在信封里），**结构化满足** `Event`，不继承、不 import trace |

| 字段 | 类型 | 谁写 | 编码约定 |
|---|---|---|---|
| `uuid` | `str` | `store.py`（落盘那一刻） | 与文件名同值；`new_event_uuid()` 造的时间递增 uuid |
| `ts` | `float` | `store.py`（写入那一刻） | Unix 秒；排序键 |
| `kind` | `str` | 调用方（tool 层） | 账名；值来自 `TraceKind` |
| `type` | `str` | 调用方（tool 层） | 粗类；值来自 `EventType` |
| `meta` | `str` | 调用方给，落盘层盖 `run_id` | **JSON 字符串**，`{run_id, source, episode_id, step}` 恰好四件 |
| `content` | `str` | 调用方 | **JSON 字符串**；判据是"存在反函数" |

`meta` 的四个键：`run_id` 由 `store._stamp_run_id` 盖在**头一个**（前置 assert：调用方带的 `meta` 不许有 `run_id` 键）；`source` 是"这条账从哪个位置发出"（图上节点名，或图外入口名如 `run_entry.new_run`）；`episode_id` / `step` 是发在哪一局、哪一步。run 级账沿用项目约定：`episode_id` 位放 run_id、`step` 恒 0。

`content` 的编码约定：标量一律 `str()`、布尔一律小写 `true` / `false`；本来就是结构化数据的那几处（`facts` / `sequence` / `verdicts` / 四本写账的正文）**直接放对象，不再 `json.dumps` 一次**（那是双重编码）。序列化只在 `LocalTrace.append` 做一处：`json.dumps(..., ensure_ascii=False)`。

### `EventType` 七类与 `TraceKind` 的关系

- `EventType`（`trace/datastore/trace_event.py`）是**字符串常量类，不是枚举**，七个值：`MODEL_CALL` / `ERROR` / `LLM_OUTCOME` / `VIEW` / `ACT` / `MEMORY_IO` / `LIFECYCLE`；合法值域的类型级表达只有一处 `EventTypeName`（`Literal[...]`）。
- `TraceKind`（`schemas/harness/domain/trace_kind.py`）是 `StrEnum`，**35 个成员**，是 harness 的账名词表，住 schemas 侧（消费者是 harness）。
- **两者不是一个概念，不能合并**：`type` 回答"这条记录相对世界 / 模型站在哪个位置"，数量极小、与链路正交；`kind` 回答"这是哪笔账"。对应关系是"每个 kind 恰好落一个 type"，**由渲染层 `tools/trace/render.py` 给出**——trace 自己不持有这张映射。封套两个都留：`type` 供廉价过滤，`kind` 供精确指认。
- 家族对应（依据 `EventType` 各常量的注释与 `render.py` 的实际用法）：`VIEW` 的 kind ∈ {`observe`, `after_action`}；`ACT` ∈ {`do_action`, `get_action_space`, `stall_check`}；`MEMORY_IO` ∈ {六条 `read_*` + 三条 `write_*`}；`LIFECYCLE` = run / episode 边界账 + `step_advance`；`MODEL_CALL` 是七条链共用的调用账；`ERROR` ∈ {`call_failed`, `call_exhausted`, `summary_parse_error`}；`LLM_OUTCOME` 与 `MODEL_CALL` 配对（`think` 与三个 `*_verdict`）。

## 五、落盘与读取

**文件布局**：一条事件一个 json 文件，路径 `<落盘根>/<uuid>.json`——**全平铺**
（不按 run 分层、也没有 `events/` 这一层，0916 起）；落盘根缺省为**进程启动目录**下的
`tracelog/`。

- 落盘根由**启动方**决定（0916 起）：`store.py` 不再从 `Path(__file__)` 回溯仓库根
  （原 `STORAGE_ROOT` 已删）——"项目仓库根在哪"不是独立第三方模块该知道的事。
  覆盖链：`LocalTrace(root=…)` / `TraceTool.build(trace_root=…)` / `build_real(trace_root=…)`。
- `LocalTrace.__init__` 建 `<root>/` **一层**（`parents=True, exist_ok=True`）。构造时**不扫盘**（`event_id` 计数器与 `id → 文件` 索引都随 `event_id` 一起下线）。
- **`run_id` 不参与路径**（0916）：它只由 `store._stamp_run_id` 盖进 `meta`——与 `memory/` 同一条规矩（一条记录一个文件，run_id 在记录里）。同一落盘根下多个 run 的事件平铺在一起，"这一批是谁的"只能问 `meta.run_id`。
- **文件名规则**：`new_event_uuid()` 造 RFC 9562 v7 布局的 uuid——前 48 位是毫秒时间戳，所以跨毫秒生成的 id 按字典序排就是按时间排；同一毫秒内那两段随机、彼此不保序。文件名的用处只有"肉眼和 `ls` 大致有序"。
- **排序真源是 `(ts, uuid)`**，不是文件名：`_scan_events()` 用 `key=lambda pair: (pair[0].ts, pair[0].uuid)` 排序。`ts` 从死字段变成排序键，"第几条"不再需要一层全局计数器，也不需要构造时扫盘接续。
- `append` 保证 **ts 严格递增**：墙上时钟分辨率有限（实测相邻两次 `time.time()` 可以取到逐字节相同的值），撞刻时人为推进 1µs——`if now <= self._last_ts: now = self._last_ts + 1e-6`。`_last_ts` 是**本实例**的序列基线，前提是 **append 单线程顺序调用**（trace 实例全图共享、图是同步 invoke）。
- 写盘走 `_atomic_write_text()`：先写 `path.with_suffix(".json.tmp")` 再 `os.replace(tmp, path)`——崩溃最多少一个未 rename 的 tmp。
- **读**：`read_events` 每次调用重扫落盘根（只扫**第一层**的 `*.json`，不递归），**不做内存缓存**。`_scan_events()` 跳过 `.tmp`，`model_validate_json` 失败的文件一律 `continue`（残文件 / 旧格式是预期内的运行期情况）。按 `meta` 筛选时用 `_meta_of(event)` 把那串 JSON 解回 dict，读不动就给空 dict——于是那条**不匹配任何条件**。

**`_Event` 与 `TraceEvent` 的对齐关系**：两者**六字段一一对应**，但 `TraceEvent` 是跨层契约、`_Event` 是 trace 私有实现，**没有继承、没有共享基类、也没有编译器保护**——改一处必须手工同步另一处。`_Event` 的 `extra="allow"` 让盘上改形之前的老 json（带 `event_id` / `schema_version` / `payload` / `frame_png` 那套）多出来的键挂在 `model_extra` 上随行；但它们缺 `uuid` / `ts`，**解析当场失败被跳过**，不会静默混进结果。

## 六、依赖边界与自包含核对

`scripts/check_trace_self_contained.py` 把"trace 自持"从一句声明变成可执行的事实。

**怎么跑**：`python scripts/check_trace_self_contained.py`——退出码 0 = 全过（实测当前三项目全过）。它只读 import 语句（AST），**不看 docstring 散文**（注释里提到 `pokemon_agent.trace` 不是依赖边）。

| 项 | 名称 | 查什么 |
|---|---|---|
| A | trace 出边为零（可整体拷走） | `trace/` 包内没有任何文件 import `pokemon_agent` 的其余部分。相对 import 先按 PEP 328 解析成绝对模块名，解析后以 `pokemon_agent.trace` 开头才算"自己" |
| B | 入口只在 `tools/`（其余层不认 trace） | `trace/` 与 `tools/` 之外的文件不许 import `pokemon_agent.trace` |
| C | `schemas/harness/domain` 不 import trace（契约层不依赖实现包） | ⚠ **不是防环**——trace 出边为零（A），任何 `X → trace` 的边都构不成回环；0916 实测四种加载顺序全不炸。守的是分层方向。B 已涵盖 C，单列是为了让失败信息直接指向哪条硬约束 |

契约层的正解是**不 import**：`TraceEvent` 用结构化满足（字段结构对得上）而不是共享类型，`TRACE_SCHEMA_VERSION` 那份"本地声明一份"的副本已随封套改造删除。

⚠ **C 项此前叫"不成环"，本轮改掉了这个名字**：那条环属于 0913 脱钩**之前**的形状（那时 `trace.store` 反向 import 契约层，实测 `ImportError`，见 `docs/PLAN_trace_decoupling.md` §3）。脱钩切掉那条边之后 trace 出边为零，"环"已无从谈起，C 剩下的意义只有**分层方向**——契约层不许反向依赖实现包。

## 七、当前状态与已知缺口

**现在成立的**：

- `LocalTrace` 是唯一实现，**磁盘账本就是唯一真相**——事件槽双写（`event_sink` + `RunDataCenter` 内存镜像）已删，读的人（图内节点）直接读盘；**另一个读者 SSE 端点随 `api.py` 0913 晚一起删了**（`api.py` 已不在仓库里）。
- 已删且不再回来的一批：`event_id`（全局单调序号 + 构造时扫盘接续 + `id → 文件` 索引）、`schema_version`（恒 `5`、零读方、两份副本要人工同步）、`frame_png`（画面真源搬到 `memory/step_memory/` 的 `before_frame` / `after_frame`）、`Source` / `SourceName`（生产者维度整体下线）、`PersistedEvent` / `project` 钩子 / `event_sink`、`TRACE_SCHEMA_VERSION`、`read_event` / `cursor` / `read_disk_events` / `void_after` / `read_screenshot`。
- `kind` 与落盘的账名现在是同一个词：`req.kind` 一路落到封套上，中间没有翻译表。

**缺口与约束**：

- **两份六字段形状靠人工同步**：`_Event` 与 `TraceEvent` 之间没有共享基类、没有编译器保护，改一处必须同步另一处。
- **平铺之后没有"run 边界"**：`read_events()` 不带 `meta` 时返回**整个落盘根**（含别的 run 的事件），调用方想只要自己那一批必须显式筛 `{"run_id": …}`——0916 之前一个 run 一个目录，这件事由路径天然保证。
- **旧格式产物没有迁移路径**（两种都不可见）：① 封套改造之前的老 json 缺 `uuid` / `ts`，`_scan_events` 解析当场失败、跳过；② 分层时代（`<run_id>/events/`）的文件根本不在扫描范围内——只扫第一层、不递归。两种都是"被静默丢弃"而不是"被读成空值"，没有迁移 / 报告工具。
- **`trace/datastore/trace_event.py` 这个文件名与它现在唯一的内容（`EventType`）不匹配**：同目录的 `event.py` 才是 `_Event` 的实现。
- **ts 严格递增依赖单实例、单线程顺序调用**：`_last_ts` 不落盘，多实例并发写同一个落盘根不保序。

## 发现的不一致

（以下以代码为准。）

1. `AGENTS.md` 九、末尾"trace 是**追加写的事件序列**……接口按'能落盘、能重放'设计"那三行连下一条弹**逐字重复了两遍**（353–355 行与 356–358 行）。
2. `AGENTS.md` 三、4 举的 trace 契约例子已过期：`event_id` 已删（现在的不变式是 `ts` 严格递增，实现为撞刻 +1µs，**不是 assert**）；"恢复 checkpoint 后断言 step 与事件序列长度一致"对应的恢复链（`cursor()` / `void_after()`）也已删。
