# spec —— Langfuse 字段适配：environment / version / input / 起止时间

> 流程位置：`langfuse-intent.md`（上轮）→ **本文件** → implementation。
> 上一轮树形/spec 见 `langfuse-spec.md`（§一~九仍然有效，本文件是其增量）。
> 定案来源：`docs/intent.md`（0927 起草、用户核对后并入本文件，原文件删除）。
> **修订 0927 22:10（用户）**：起止时间由"只记 elapsed_ms"改为**记 started_at /
> ended_at 双时刻、封套删除 ts、全部排序改用 ended_at**。

## 一、定案（用户 2026-09-27 拍板）

1. **environment / version 占位**：`environment="local"`（b 案——SDK 约束 environment
   只许小写字母数字+连字符+下划线，`0.1.0` 带点不合规），`version="0.1.0"`。
2. **起止时间走档一，且记双时刻**：调用处记 `started_at` / `ended_at` 进封套；
   **封套删除 `ts`**；**排序键全部改 `ended_at`**；ingestion API 直打（档二）不做、
   单独立项。
3. **input 三分**（七条 generation 已有、六条 RAG 投 query、其余 None），
   六条读口 `as_type="retriever"`（intent 建议项，按此执行）。

## 二、时间字段的事实与改造（落码前钉死，勿再猜）

### 2.1 现状事实

- 封套 `ts` 在 **append 时刻**打：`LangfuseTrace.append` → `_next_timestamp()`
  （langfuse_trace.py:100、173-175，`time.time()` 进程内单调化）；LocalTrace 在
  `store.py:162` 同口径。ts ≈ 记账时刻，紧跟操作结束，**没有操作起点**。
- 操作真实起止全链路无人记：`brain/brain.py` 12 处 `ModelCall(payload=…)` 只有
  token/raw/prompt/images/ok；`ModelCall` docstring 的"延迟"一词过期（落码顺手修）。
- OTEL span 的 start/end 都≈append 瞬间 → UI 时长条无意义（档一接受，真值在封套）。

### 2.2 改造：封套 `{ts}` → `{started_at, ended_at}`

- 新封套：`{uuid, kind, type, started_at, ended_at, meta, content}`，两个时刻都是
  **wall clock `time.time()` 的 float**（要参与排序与血缘切分，必须可跨进程比较，
  不用 monotonic）。`store.py` / `datastore/event.py` 的 `schema_version` 5→6
  （两份副本人工同步的口径不变）。
- **值的三层来源**：

| 层 | 谁取时 | 语义 |
|---|---|---|
| 模型账（重试链每条调用各自） | `brain/brain.py` 12 处：provider `complete()` 前后 | `payload["started_at" / "ended_at"]` 直存 float（`ModelCall.payload` 类型放宽为 `dict[str, str \| float \| list[str]]`）；`render.model_call` 整体透传 + 提升到封套 |
| 六条 RAG 读口 | 7 个检索节点：MemoryTool 查询前后 | `FromHarnessToTraceToolAppendReq` 新可选字段 `started_at` / `ended_at`（float），`render.retrieve_node` 透传 |
| 其余全部账 | 调用方不给 → `TraceTool.append` 落账时补 | `started_at = ended_at =` append 时刻（机械账的"操作"就是记账本身，起点终点同一瞬） |

- 机制：`Rendered` 加可选 `started_at` / `ended_at`；tool 层组封套时优先用
  Rendered 的值，缺省补 now；`_next_timestamp()` 单调化机制随 ts 一起删除。
- **排序**：现有 `(ts, uuid)` 六处排序/比较点全部改 `(ended_at, uuid)`：
  `langfuse_trace.read_events`、`store.py:222`、`tools/trace/lineage.py:76/85/95`
  （fork 时刻 = checkpoint_save 账的 `ended_at`）、`tools/trace/__init__.py:307/310`
  （恢复线切分边界 `(e.ts, …) <= (fork.ts, …)` 同换）、smoke/rehearsal/tests 断言。
  `Event` / `ParsedEvent` / `Fork` 数据类字段同步改名（`ts` → 双时刻或仅 `ended_at`，
  按各自读方需要最小化）。
- **兼容性**：Langfuse 里 schema 变更前写入的旧账 decode 失败、被 `read_events`
  过滤——可接受：历史真源在 `_to_delete/tracelog_legacy_0927/` 本地归档，Langfuse
  本身 0927 才启用。`decode_observation_event` 改读新键。
- `run_end`/`run_error` 落 span 前 sleep 3ms **删除**（修订 22:18，用户）：排序权威
  在封套 `ended_at`，OTEL UI 的同毫秒兄弟序只是显示面，不再做时间补偿。

## 三、字段设计

### 1. environment / version

| 项 | 值 | 落点 |
|---|---|---|
| environment | `"local"` | `build_client_from_environment()` 构造 `Langfuse(environment="local")`，client 级一次全 run 生效 |
| version | `"0.1.0"` | `LangfuseTrace.append` 逐账传 `version=…`；scope 锚（branch/run/episode/step，含 fake）与错误事件统一带 |

常量定义在 `langfuse_support.py`（`LANGFUSE_ENVIRONMENT_NAME = "local"`、
`LANGFUSE_ADAPTER_VERSION = "0.1.0"`），不留字面量副本。落码时核对 SDK
`create_event` 是否收 `version`（错误事件路径）——不收则错误账改走
`start_observation(as_type="event", version=…)`，或接受错误账缺 version。

### 2. input 三分（判据：Langfuse 惯例 input=请求面）

| 类别 | 账 | input | as_type |
|---|---|---|---|
| 7 条模型调用 | sense/choose/plan/decompose/judge/summarize×2 | `generation_input_fields`（prompt/images，现状保持） | generation |
| 6 条 RAG 读口 | `read_act_memory` / `read_episode_memory` / `read_knowledge` / `read_object_memory` / `read_task_memory` | `retrieve_input_fields`：投 `query`（refs 不重复投，封套里有） | **retriever** |
| 其余全部 | 机械事实 / state / 生命周期 / 错误账 | `None`（删 `{local_event_uuid}` 占位，真身已在 metadata） | span / event（现状） |

`retrieve_input_fields(content)` 加在 `langfuse_support.py`，与
`generation_input_fields` 同款口径：缺键退空、封套本体仍唯一真源。

### 3. 起止时间（档一：双时刻进封套）

见 §2.2。要点：wall clock float、三层来源、缺省补 now、排序与血缘切分全改
`ended_at`。Langfuse UI 时间轴维持≈append（SDK 不暴露 start_time，档二不立项）；
真实起止以封套为准，UI 时长条无意义是已接受的限制。

## 四、改动清单

| 文件 | 改动 |
|---|---|
| `trace/langfuse_support.py` | ① `environment="local"`；② 两个版本常量；③ `LangfuseClientPort` 补 `version`；④ `retrieve_input_fields()`；⑤ `new_event_envelope` 双时刻；⑥ `decode_observation_event` 读新键 |
| `trace/langfuse_trace.py` | append kwargs 加 `version`；input 三分；读口 `as_type="retriever"`；scope 锚带 version；删 `_next_timestamp`，排序改 `ended_at` |
| `trace/interface/event.py` | `Event` 字段 `ts` → `started_at` / `ended_at` |
| `trace/store.py` + `trace/datastore/event.py` | LocalTrace 双时刻落盘、排序改 `ended_at`、`schema_version` 5→6 |
| `brain/brain.py` | 12 处组账点前后取 `time.time()` → payload 双时刻；`ModelCall.payload` 类型放宽加 float；修 ModelCall docstring 过期"延迟"文案 |
| `schemas/harness/communication/FromHarnessToTraceToolAppendReq.py` | 加 `started_at` / `ended_at: float \| None = None` |
| `tools/trace/render.py` | `Rendered` 加可选双时刻；`model_call` 从 payload 提升；`retrieve_node` 从 req 透传；其余 renderer 缺省 None |
| `tools/trace/parse.py` | `ParsedEvent` 字段同步 |
| `tools/trace/lineage.py` / `tools/trace/__init__.py` | 排序与 fork 边界改 `ended_at` |
| `harness/{task,run,episode}/…` 7 个检索节点 | 查询前后取时 → req 双时刻 |
| `tests/_fake_langfuse.py` | Fake client 收 `version`、记录 `input`/`as_type` |
| `tests/test_langfuse_trace.py` + render/parse 相关 | input 三分、version、retriever、双时刻与排序断言 |
| `scripts/langfuse_smoke.py` / `langfuse_tree_rehearsal.py` | 排序断言改 `ended_at`；input/version 抽查 |

## 五、验证

1. pytest 定向全绿 + ruff 干净（遵守 basetemp 规则）。
2. smoke 全过：generation input 不变；六条读口 as_type=retriever、input 可见
   query；非模型账 input 空；version 全账 `"0.1.0"`；模型账封套双时刻有序且
   `started_at < ended_at`；机械账双时刻相等；read_events 按 `ended_at` 有序。
3. Docker 服务起后跑 rehearsal，UI 核对：environment=`local`、version=`0.1.0`、
   retriever 图标；树序以封套 `ended_at` 为准核对（UI 同毫秒兄弟序不再特殊处理）。

## 六、明确不做

- OTEL/UI span 时间轴回拨（ingestion API，档二）不做。
- LocalTrace 磁盘格式迁移不做（旧 tracelog 已归档，schema_version 升 6 断代）。
- environment/version 真实取值体系（按执行通道区分等）等占位跑通后再议。
- 记忆/brain 侧零行为变更：brain 只多两个只写进 payload 的时刻字段，无状态铁律不涉。
