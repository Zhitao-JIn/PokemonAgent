# trace —— 模块规格

> sense_call 已停止产出，旧账仍可读；TraceKind 与解析、渲染映射保持兼容。

> 最后更新：2026-10-22 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/trace/` 是一个**独立的第三方模块**：事件流的存储实现 + 它自己的港口协议 + 形状协议 + 粗类词表。项目侧把它当"拷走即可复用"的成品对待。存储可选本地 JSON 文件或本机自托管 Langfuse；Langfuse 不创建 LocalTrace 副本。

- **只保证一件事**：按时间记账。`type` / `kind` / `meta` / `content` 的**合法值域是声明方的事，trace 不认识**——所以 `TracePort.append()` 的前两个参数是裸 `str`。
- **`meta` / `content` 是不透明载荷**：trace 只负责序列化成 JSON 字符串存储、读回时原样交还，**不解释里面装了什么**。
- **零出边**：包内任何文件不 import `pokemon_agent` 的其余部分（可执行核对见 `scripts/check_trace_self_contained.py` 的 A 项）。
- **入边只在 tool 层**：其余各层（`brain` / `harness` / `memory` / `world` / `schemas` / `vision` 与装配点 `build.py`）一律不 import 它——harness 只经 runtime 的 `trace`（`TraceToolPort`）说话（B 项）。
- 统一出口 `trace/__init__.py` re-export：`Event`、`EventType`、`LocalTrace`、`LangfuseTrace`、`TracePort`、`new_event_uuid`。消费方写 `from pokemon_agent.trace import LocalTrace, TracePort`。

## 二、目录结构

```
trace/
├── __init__.py              统一出口（上面六个名字）
├── store.py                 TracePort 的本地文件实现 LocalTrace + uuid
├── langfuse_trace.py        本机自托管 Langfuse TracePort 实现
├── langfuse_support.py      SDK 边界、封套编解码、查询与 observation 辅助函数
├── interface/
│   ├── __init__.py          出口：Event / TracePort
│   ├── event.py             Event（形状协议，八属性）
│   └── trace_port.py        TracePort（runtime_checkable Protocol）
└── datastore/
    ├── __init__.py          出口：EventType
    ├── event.py             _Event（trace 私有的具体实现，不进 __all__）
    └── trace_event.py       EventType（七个字符串常量）+ EventTypeName（Literal）
```

`_Event` 只服务 `store.py`（它 `from .datastore.event import _Event`），**不进任何 `__all__`**；外部一律通过 `Event` 协议说话。

## 三、TracePort 契约

`TracePort`（`trace/interface/trace_port.py`，`@runtime_checkable Protocol`）提供事件追加、查询与后端生命周期方法，签名里全是不带值域的裸类型。

| 方法 | 签名 | 承诺 |
|---|---|---|
| `append` | `(type: str, kind: str, meta: dict[str, Any] \| None = None, content: Any = None, *, started_at: float \| None = None, ended_at: float \| None = None) -> str` | 追加一条事件，返回本地 `uuid` |
| `read_events` | `(meta: dict[str, Any] \| None = None) -> list[Event]` | 读当前 backend 可见事件，按 `(ended_at, seq)` 升序，可按 `meta` 做交集筛选 |
| `flush` | `() -> None` | 刷新后端缓冲；LocalTrace 为空操作 |
| `shutdown` | `() -> None` | 关闭后端资源；LocalTrace 为空操作 |

- `append` **前置条件**：`meta` 由调用方（tool 层）交齐——**已含 `run_id` / `branch`**（0927 定案：执行线标识由 tool 层在调用时盖，存储实现只透传、不补盖、不 assert 任何键）。**后置条件**：事件被 backend 接受；LocalTrace 在返回前落盘，LangfuseTrace 返回仅代表 SDK 接受并异步投递。
- `read_events` **筛选语义**：`None` / 空 dict = backend 当前可见事件；给了就只返回**每个键都相等**的那批——AND-of-equalities，不支持 OR 或大小比较。事件缺某键时不匹配。
- `read_events` **后置条件**：按 `(ended_at, seq)` 升序；无匹配返回空列表。读取失败原样抛出。
- 读能力只剩这一条通用读方法：不做掩码、不做游标、不打标，只回答"盘上有什么"。
- 已下线的入口（现在不存在）：`read_event(event_id)`——画面真源搬到 `memory/step_memory/` 之后没有读者；`cursor()` / `read_disk_events()` / `void_after()`——随 checkpoint 恢复链删；`read_screenshot`——随截图副本删。
- 实现 `LocalTrace(root: Path | str | None = None)`：`root` 是**落盘根**
  （一条事件一个文件那个目录），缺省为**进程启动目录**下的 `tracelog/`（`Path.cwd()`，0916 起）。
  本类**不持有 `run_id` / `branch`**（0927 定案）：执行线标识由 tool 层盖进 `meta`，本类只透传。
  生产路径的覆盖链：
  `paths.trace`（配置文件）→ `build_real(config=…)` → `TraceTool.build(run_id=…, trace_root=…, branch=…, backend=…)` → 这里；
  测试直接传 `tmp_path`。

## 四、事件形状

一条事件**八个字段，一个都不多**。三处形状必须逐字段对齐（**没有编译器保护**）：

| 处 | 文件 | 角色 |
|---|---|---|
| 协议 | `trace/interface/event.py::Event` | 结构化声明：trace 记账真正需要的八样 |
| trace 实现 | `trace/datastore/event.py::_Event` | trace 私有 Pydantic 实现，`model_config = ConfigDict(extra="allow")` |
| 项目侧 | `schemas/harness/domain/trace_event.py::TraceEvent` | 跨层数据形状（出现在信封里），**结构化满足** `Event`，不继承、不 import trace |

| 字段 | 类型 | 谁写 | 编码约定 |
|---|---|---|---|
| `uuid` | `str` | 存储实现 | LocalTrace 中与文件名同值；Langfuse 用它回链项目事件 |
| `seq` | `int` | 存储实现（`next_seq()`） | 进程内全局 append 的单调序号；同刻 `ended_at` 的决胜键 |
| `kind` | `str` | 调用方（tool 层） | 账名；值来自 `TraceKind` |
| `type` | `str` | 调用方（tool 层） | 粗类；值来自 `EventType` |
| `started_at` | `float` | 调用方交，缺省存储实现补 | 操作真实开始时刻；没交 = 记账时刻 |
| `ended_at` | `float` | 调用方交，缺省存储实现补 | 操作结束时刻；**排序键的一半**（`(ended_at, seq)`） |
| `meta` | `str` | 调用方给，tool 层盖 `run_id` / `branch` | **JSON 字符串**，包含执行线与事件位置 |
| `content` | `str` | 调用方 | **JSON 字符串**；判据是"存在反函数" |

`meta` 的键：`run_id`、`branch` 由 **tool 层**盖章（`TraceTool.append` 的 `_stamp_meta`，存储实现只透传）；`source` 是"这条账从哪个位置发出"；`episode_id` / `task_id` / `step` 描述运行位置。run 级账沿用项目约定：`episode_id` 与 `task_id` 位放 run_id、`step` = 已派局数；episode 级账 `task_id` 位放 episode_id。

`content` 的编码约定：标量一律 `str()`、布尔一律小写 `true` / `false`；本来就是结构化数据的那几处（`facts` / `sequence` / `verdicts` / 四本写账的正文）**直接放对象，不再 `json.dumps` 一次**（那是双重编码）。序列化只在 `LocalTrace.append` 做一处：`json.dumps(..., ensure_ascii=False)`。

### `EventType` 七类与 `TraceKind` 的关系

- `EventType`（`trace/datastore/trace_event.py`）是**字符串常量类，不是枚举**，七个值：`MODEL_CALL` / `ERROR` / `LLM_OUTCOME` / `VIEW` / `ACT` / `MEMORY_IO` / `LIFECYCLE`；合法值域的类型级表达只有一处 `EventTypeName`（`Literal[...]`）。
- `TraceKind`（`schemas/harness/domain/trace_kind.py`）是 `StrEnum`，**51 个成员**，是 harness 的账名词表，住 schemas 侧（消费者是 harness）。
- **两者不是一个概念，不能合并**：`type` 回答"这条记录相对世界 / 模型站在哪个位置"，数量极小、与链路正交；`kind` 回答"这是哪笔账"。对应关系是"每个 kind 恰好落一个 type"，**由渲染层 `direct/trace/render.py` 给出**——trace 自己不持有这张映射。封套两个都留：`type` 供廉价过滤，`kind` 供精确指认。
- 家族对应（依据 `EventType` 各常量的注释与 `render.py` 的实际用法）：`VIEW` 的 kind = `sense_frame`；`ACT` ∈ {`act_call`, `get_action_space`, `check_stall`}；`MEMORY_IO` ∈ {六条 `read_*` + 五条 `write_*`}；`LIFECYCLE` = 三层边界账 + `settle_goal` / `settle_task` + `advance_step` + `checkpoint_save` / `checkpoint_restore` + `review_inject` / `review_audit` + `budget_clamped` / `budget_skipped`；`MODEL_CALL` 是九条链共用的调用账；`ERROR` ∈ {`call_failed`, `call_exhausted`, `summary_parse_error`, `checkpoint_error`}；`LLM_OUTCOME` 与 `MODEL_CALL` 配对（`choose_verdict` 与三个 `*_verdict`）。

## 五、落盘与读取

**文件布局**：一条事件一个 json 文件，路径 `<落盘根>/<uuid>.json`——**全平铺**
（不按 run 分层、也没有 `events/` 这一层，0916 起）；落盘根缺省为**进程启动目录**下的
`tracelog/`。

- 落盘根由**启动方**决定（0916 起）：`store.py` 不再从 `Path(__file__)` 回溯仓库根
  （原 `STORAGE_ROOT` 已删）——"项目仓库根在哪"不是独立第三方模块该知道的事。
  覆盖链：配置文件的 `paths.trace` → `build_real(config=…)` → `TraceTool.build(trace_root=…)` → `LocalTrace(root=…)`。
- `LocalTrace.__init__` 建 `<root>/` **一层**（`parents=True, exist_ok=True`）。构造时**不扫盘**（`event_id` 计数器与 `id → 文件` 索引都随 `event_id` 一起下线）。
- **`run_id` 不参与路径**（0916）：它由 **tool 层**的 `_stamp_meta` 盖进 `meta`（存储实现只透传）——与 `memory/` 同一条规矩（一条记录一个文件，run_id 在记录里）。同一落盘根下多个 run 的事件平铺在一起，"这一批是谁的"只能问 `meta.run_id`。
- **文件名规则**：`new_event_uuid()` 造 RFC 9562 v7 布局的 uuid——前 48 位是毫秒时间戳，所以跨毫秒生成的 id 按字典序排就是按时间排；同一毫秒内那两段随机、彼此不保序。文件名的用处只有"肉眼和 `ls` 大致有序"。
- **排序真源是 `(ended_at, seq)`**，不是文件名：`_scan_events()` 用 `key=lambda pair: (pair[0].ended_at, pair[0].seq)` 排序。`seq` 是**进程内全局计数器**（`trace/seq.py` 的 `next_seq()`，双后端共享、重启置零、不持久化）：先按操作**结束时刻**排，同刻按 append 序决胜；`uuid` 退化成纯标识（旧 `(ts, uuid)` 会在同刻把执行序洗牌）。
- `append` 不承诺时钟严格递增：`started_at` / `ended_at` 调用方交了就用、没交补记账时刻（`time.time()` 同值完全可能），**同刻决胜靠 `seq`**。跨进程不保序——各进程各一个计数器。
- 写盘走 `_atomic_write_text()`：先写 `path.with_suffix(".json.tmp")` 再 `os.replace(tmp, path)`——崩溃最多少一个未 rename 的 tmp。
- **读**：`read_events` 每次调用重扫落盘根（只扫**第一层**的 `*.json`，不递归），**不做内存缓存**。`_scan_events()` 跳过 `.tmp` 与非文件条目（同名目录），只对 `ValidationError` / `UnicodeDecodeError` `continue`（残文件 / 旧格式 / 编码坏掉是预期内的运行期情况）；**权限与 IO 读取失败原样抛出**，不静默少一条。按 `meta` 筛选时用 `_meta_of(event)` 把那串 JSON 解回 dict，读不动就给空 dict——于是那条**不匹配任何条件**。

**读侧解析层（0925，CHANGELOG 259）**：`trace/` 只管封套，正文是字符串化的 JSON。要按类型读正文的
一方（测评 `evals/`）走 `pokemon_agent/direct/trace/parse.py::parse(event) -> ParsedEvent`：按 `kind` 分派
`direct/trace/content.py` 的正文模型（与 `render.py` 逐字段对照，除调用账外 `extra="forbid"`），
`sense_frame` 的 `facts` / `place` / `ram` 读回 `Facts` / `PlaceInWorld` / `RamReadout`；没建模的账读成
`OtherContent`。模型住产出方（谁渲染谁定义），`tests/direct/trace/test_trace_parse.py` 做写 → 读回环。

**`_Event` 与 `TraceEvent` 的对齐关系**：两者**八字段一一对应**，但 `TraceEvent` 是跨层契约、`_Event` 是 trace 私有实现，**没有继承、没有共享基类、也没有编译器保护**——改一处必须手工同步另一处。机械保障两处（都在默认测试集里）：`tests/trace/test_trace_event_protocol.py`（协议 ↔ 盘上记录的键）与 `tests/direct/trace/test_trace_event_alignment.py`（`TraceEvent` 字段集合 == `Event` 属性集合）。`_Event` 的 `extra="allow"` 让盘上改形之前的老 json（带 `event_id` / `schema_version` / `payload` / `frame_png` 那套）多出来的键挂在 `model_extra` 上随行；但它们缺 `uuid` / `seq` / `ended_at` 等必填字段，**解析当场失败被跳过**，不会静默混进结果。

## 六、依赖边界与自包含核对

`scripts/check_trace_self_contained.py` 把"trace 自持"从一句声明变成可执行的事实。

**怎么跑**：`python scripts/check_trace_self_contained.py`——退出码 0 = 全过。它只读 import 语句（AST），**不看 docstring 散文**（注释里提到 `pokemon_agent.trace` 不是依赖边）。实测（2026-10-22）：A / C 过，**B 挂**——脚本退出码 1，B 项报 6 处 violation。

| 项 | 名称 | 查什么 |
|---|---|---|
| A | trace 出边为零（可整体拷走） | `trace/` 包内没有任何文件 import `pokemon_agent` 的其余部分。相对 import 先按 PEP 328 解析成绝对模块名，解析后以 `pokemon_agent.trace` 开头才算"自己" |
| B | 入口只在 `tools/`（其余层不认 trace） | **已知过时（2026-10-22，待另案处理）**：豁免目录仍写 `trace/` 与 `tools/` 两个顶层目录，而 tool 层现在住 `direct/trace/`（另有 `reviewer/__main__.py` 也 import trace）。当前 violation：`direct/trace/__init__.py`、`direct/trace/budget_render.py`、`direct/trace/render.py`、`reviewer/__main__.py` 共 6 处 import `pokemon_agent.trace`。修法是把豁免目录改成现状，本轮只标记、不动脚本 |
| C | `schemas/harness/domain` 不 import trace（契约层不依赖实现包） | ⚠ **不是防环**——trace 出边为零（A），任何 `X → trace` 的边都构不成回环；0916 实测四种加载顺序全不炸。守的是分层方向。B 已涵盖 C，单列是为了让失败信息直接指向哪条硬约束 |

契约层的正解是**不 import**：`TraceEvent` 用结构化满足（字段结构对得上）而不是共享类型，`TRACE_SCHEMA_VERSION` 那份"本地声明一份"的副本已随封套改造删除。

⚠ **C 项此前叫"不成环"，本轮改掉了这个名字**：那条环属于 0913 脱钩**之前**的形状（那时 `trace.store` 反向 import 契约层，实测 `ImportError`，见 `docs/PLAN_trace_decoupling.md` §3）。脱钩切掉那条边之后 trace 出边为零，"环"已无从谈起，C 剩下的意义只有**分层方向**——契约层不许反向依赖实现包。

## 七、当前状态与已知缺口

**现在成立的**：

- LocalTrace backend 使用平铺 JSON 磁盘账本；显式选择 Langfuse backend 时，本机自托管 Langfuse 是唯一持久层，事件经 SDK 异步发送并接受 API 最终一致性，不创建 LocalTrace 副本。
- 已删且不再回来的一批：`event_id`（全局单调序号 + 构造时扫盘接续 + `id → 文件` 索引）、`schema_version`（恒 `5`、零读方、两份副本要人工同步）、`frame_png`（画面真源搬到 `memory/step_memory/` 的 `before_frame` / `after_frame`）、`Source` / `SourceName`（生产者维度整体下线）、`PersistedEvent` / `project` 钩子 / `event_sink`、`TRACE_SCHEMA_VERSION`、`read_event` / `cursor` / `read_disk_events` / `void_after` / `read_screenshot`。
- `kind` 与落盘的账名现在是同一个词：`req.kind` 一路落到封套上，中间没有翻译表。

**缺口与约束**：

- **两份八字段形状靠人工同步**：`_Event` 与 `TraceEvent` 之间没有共享基类、没有编译器保护，改一处必须同步另一处。机械保障两处：`tests/trace/test_trace_event_protocol.py`（协议 ↔ 盘上记录的键）与 `tests/direct/trace/test_trace_event_alignment.py`（`TraceEvent` 字段集合 == `Event` 属性集合）。
- **平铺之后没有"run 边界"**：`read_events()` 不带 `meta` 时返回**整个落盘根**（含别的 run 的事件），调用方想只要自己那一批必须显式筛 `{"run_id": …}`——0916 之前一个 run 一个目录，这件事由路径天然保证。
- **旧格式产物没有迁移路径**（两种都不可见）：① 封套改造之前的老 json 缺 `seq` / `ended_at` 等必填字段，`_scan_events` 解析当场失败、跳过；② 分层时代（`<run_id>/events/`）的文件根本不在扫描范围内——只扫第一层、不递归。两种都是"被静默丢弃"而不是"被读成空值"，没有迁移 / 报告工具。
- **`trace/datastore/trace_event.py` 这个文件名与它现在唯一的内容（`EventType`）不匹配**：同目录的 `event.py` 才是 `_Event` 的实现。
- **`seq` 是进程内计数器，跨进程不保序**：`next_seq()` 每进程一个、重启置零，两个进程同时写一个落盘根（或重启后接着写）时，同刻账的决胜次序没有保证。

## 发现的不一致

（以下以代码为准。）

1. ~~`AGENTS.md` 九、末尾"trace 是**追加写的事件序列**……接口按'能落盘、能重放'设计"那三行连下一条弹**逐字重复了两遍**~~——**已了结**：586 整段同步 `AGENTS.md` / `CLAUDE.md` 第九节后，该段现在只剩一份（`AGENTS.md` 第九节末尾）。
2. `AGENTS.md` 三、4 举的 trace 契约例子仍写过时细节：`TraceTool.append()` 入口断言写成"`req.meta` 带齐 `source`/`episode_id`/`step` 且不带 `run_id`"——实际断言是**四件**（还有 `task_id`），"不带 `run_id`"那半句仍成立（`branch` 也不许带）；`event_id` 与恢复链（`cursor()` / `void_after()`）的说法已不在该节，本条只剩"三件 vs 四件"这一处。`AGENTS.md` 不在本文档改动范围内，仅记录。
