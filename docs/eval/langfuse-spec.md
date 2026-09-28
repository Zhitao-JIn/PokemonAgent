# spec —— LangfuseTrace：本机唯一 trace 存储

> 流程位置：`langfuse-intent.md` → **langfuse-spec.md** → `langfuse-plan.md` → implementation
> 状态：实现规格；本机自托管 Langfuse 是唯一 trace 存储，本规格不保留 LocalTrace 双写
> 最后更新：2026-09-27
> 关联：`docs/eval/langfuse-intent.md`、`docs/spec/trace/SPEC.md`、`pokemon_agent/trace/`

---

## 一、目标与非目标

实现 `pokemon_agent.trace.LangfuseTrace`，结构化实现现有 `TracePort`。它使用 Langfuse Python SDK v4 将项目事件写入本机自托管 Langfuse，并通过 Langfuse Observations API v2 查询和还原事件。trace 事件不再写入本地 JSON 文件；不与 `LocalTrace` 双写，也不建立本地事件副本 / outbox。

本机 Langfuse 服务端负责持久化，SDK 负责将 observations 异步发送到服务端。这里的“本机”指本机自托管服务，不表示 SDK 自身会把事件先写入本地磁盘。SDK 队列不是耐久存储；进程被强制终止时尚未发出的数据可能丢失。

本规格不实现线上 Langfuse、Inspect AI 集成、评分写入、服务部署 / Docker Compose、自动补传队列或 Langfuse Dashboard 定制。

## 二、边界和依赖

- `LangfuseTrace` 位于 `pokemon_agent/trace/`，只依赖标准库、现有 trace 模块和 `langfuse` SDK；不 import `pokemon_agent` 的其他模块。项目事件的 `kind` / `type` 词表仍由 `tools/trace/` 维护。
- `TraceTool` 仍是 `TraceToolPort` 唯一实现和 trace 事件转换边界；通过 `TraceTool.build(backend="langfuse", ...)` 选择实现。`backend="local"` 保留给离线测试、开发，默认行为不变。
- 新增运行依赖 `langfuse>=4.7,<5`。自托管端要求 Langfuse v4，以使用 Observations API v2；配置通过 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL` 提供。Langfuse 模式缺少凭据或配置不合法时，装配显式失败，不静默切回本地实现。
- 本机自托管服务不可用时，SDK 按自身重试 / 批处理策略发送；本模块不另建磁盘 outbox。由于 Langfuse 是唯一持久化真源，服务端持续不可用或进程在 SDK 队列发送前退出可能造成观测缺失。checkpoint 恢复状态不受此影响。

## 三、TracePort 事件编码

Langfuse observation metadata 携带一份可逆的项目事件封套：

```json
{
  "pokemon_trace": {
    "uuid": "<local-event-uuid>",
    "kind": "<kind>",
    "type": "<type>",
    "ts": 0.0,
    "meta": {"run_id": "...", "branch": "...", "source": "..."},
    "content": {}
  }
}
```

- `uuid` 由 trace 实现用现有时间排序 UUID 生成；它不是 Langfuse observation ID。写入成功排队后 `append()` 返回此 UUID。
- `ts` 是 Unix 秒，写入时生成并在同一实例内保证严格递增；所有 `read_events()` 按 `(ts, uuid)` 升序排序。分支并发写入之间只保证按记录时间排序，不承诺跨进程的全序。
- `meta` 的 `run_id` / `branch` 由 tool 层（`TraceTool.append`）在调用时盖入头两个位置（0927 定案）；调用方不得自带这两个键，trace 后端对执行线身份零持有、只透传。其余键原样保留。`content` 作为原始 JSON 值完整往返，保障 `TraceTool.parse()`、机械评测和 checkpoint 血缘读取兼容。
- `local_event_uuid` 可同时作为便于 Langfuse UI/API 过滤的扁平 metadata 字段；规范事件封套以 `pokemon_trace` 为准。
- observation `name` 使用事件 `kind`；`metadata` 还包含 `event_type`、完整 meta 标签及 `local_event_uuid`。generation 的 usage 可由 content 中明确的 token 计数投影，正文封套仍保留原始事件。generation 的 `input` 从 content 引入请求面（`prompt` / `images`）供 Dashboard 直读——封套本体仍是唯一真源。
- Langfuse 当前 SDK 创建 observation 时支持 generation / span 等类型，不把 Langfuse observation ID 改写成本地 UUID。非模型事件以 span 表达，模型调用账（`type == "model_call"`）以 generation 表达。错误账使用 Langfuse ERROR level event。generation 不做 SDK 自动模型 instrumentation，避免同一调用重复记录。

完整 `content` 在本阶段只发送到配置的本机自托管实例，Cloud 外发关闭。当前 trace 正文会包含项目现有账本中已有的模型 I/O、决策和记忆正文；不新增截图、ROM、模拟器状态或完整记忆库采集。线上连接若未来启用，必须另行批准数据策略。

## 四、Trace ID、观测层级与父节点

### Trace ID

- 同一个 `run_id` 用 SDK `create_trace_id(seed=run_id)` 确定性得到一个 Langfuse trace ID；不同 `run_id` 生成不同 trace ID。
- 每个事件都把该 ID 放入显式 `trace_context`，不依赖隐式 ContextVar 跨图节点传播。
- `run_id`、`branch`、`episode_id`、`task_id`、`step`、`source` 与本地 UUID 放在 observation metadata，作为查询和回链字段。

### 父子层级

物理父子关系按以下最近有效作用域建立：

```text
branch:<branch>（每个实例首笔账时建，顶层锚）
└── run_start（真账；注册为 run 层锚）
    ├── run 层账（perceive/plan/settle_goal/run_end…）
    ├── episode_start（真账；注册为 episode 层锚）
    │   ├── episode 层账（decompose/settle_task/verify/summarize/episode_end…）
    │   ├── task_start（注册为 task 层锚）
    │   │   ├── step:N scope（每 task/step 一个）
    │   │   │   ├── generation（model_call）
    │   │   │   └── span（其他事件）
    │   │   ├── checkpoint_save、task_end…
    ├── episode_start（第二个 episode，与 ep-1 平级）
```

- **branch scope 是顶层锚**：每个实例首笔 append 时创建（构造期不落 observation）；
  恢复线因此没有"构造即建"的第二个空壳 run root。
- **start 账即 scope**：`run_start` / `episode_start` / `task_start` 既是事件账也是
  该层锚，各自注册进实例的 scope 索引；后续事件按 `episode_id`、`task_id`、`step`
  找最近有效 scope。run 层账（episode_id 为空）挂 `run_start` 锚下。
- **恢复线伪造缺失的祖先锚**：恢复线首笔账 `checkpoint_restore` 的 content 带
  恢复级别（`CheckpointMark.level`）。`level="episode"`：伪造一层 `run_start (fake)`
  scope（挂 branch scope 下，metadata `synthetic=true`），恢复账与后续真
  `episode_start` 都挂它下面；`level="task"`：连伪造两层——`run_start (fake)` 之后
  用恢复账 meta 里的 `episode_id` 当场伪造 `episode_start (<ep-id>) (fake)`，
  `checkpoint_restore` 挂伪造 episode 锚下（"加两层再挂"，0927 定稿）；meta 缺
  `episode_id` 时退回懒伪造（恢复账先挂 run 锚，等第一笔带号的账再补 episode 锚），
  `task_start`/`episode_end`/`step` 都挂 episode 锚下，`run_end` 挂伪造 `run_start (fake)`
  下、整树最后一笔；`level="run"`：不伪造——`begin` 重记真 `run_start`
  （与恢复账并列挂 branch scope），后续照常挂真账。伪造 scope 只当父锚、名字带
  `(fake)` 后缀、不带事件封套、`read_events` 读不到。
- **血缘不在树边上**：谁从哪个 checkpoint 分出，由账本 meta（`checkpoint_restore`
  与同 id `checkpoint_save` 的 `checkpoint_id` + `branch`）推出
  （`tools/trace/lineage.py`），树形不承载、也不影响这条推导；本地 JSON backend
  无层级概念，血缘照推。branch scope metadata 另带 `parent_checkpoint_id` 仅作
  Dashboard 可读性标注。
- observation ID 由 Langfuse SDK 生成。checkpoint ID 与本地事件 UUID 都只作关联 metadata。
- task / episode / run 结束事件按自己的本地事件时间写入 scope；SDK v4 使用已支持的 span / generation/event API，不依赖旧版 `trace()` / `span()` / `generation()` 接口。

## 五、append、查询和一致性

### append

1. 校验 meta 已带 tool 层盖好的 `run_id` / `branch`（缺了当场拒绝）。
2. 生成本地 UUID 和单调递增 `ts`，序列化事件封套。
3. 在指定 parent observation context 下创建 span / generation observation，metadata 写入完整封套。
4. 正常退出 SDK observation context 后返回本地 UUID。SDK 向本机服务异步发送；`append()` 不承诺此刻已可通过 API 查到。
5. SDK 自身可捕获并记录传输错误；LangfuseTrace 不用 LocalTrace 做隐式回退。服务端不可用时，UI/API 可能缺观测；不会因此篡改 checkpoint 或 harness 的执行状态。

### read_events

- `read_events(meta)` 查询当前 `run_id` 的 trace ID，通过 Observations API v2 分页取回 observations，解码 `pokemon_trace` 封套，再应用 AND-of-equalities 的精确 meta 过滤。
- `None` / 空 dict 返回本 run trace 中当前可见的全部事件；`{"run_id": ...}` 仍按精确相等过滤。由于一个 `LangfuseTrace` 实例绑定一个 run，查询不会枚举其他 run 的 traces。
- 查询按 `(ts, uuid)` 排序；分页完成后才返回，API 查询失败原样抛出，不返回伪造的空成功结果。
- **接受最终一致性**：SDK `flush()` 表示队列内容已发送给 API，不保证服务端 ingestion 和 Observations API 已立即可查。刚 append 的事件可能暂时不在 read_events 结果中；调用方不应把立即读回作为 append 后置条件。需要完整 run 观测时，在运行边界 flush 后再通过 API 查询；UI/API 最终可见性由 Langfuse 服务端完成。
- TraceTool 的 branch lineage 算法仍消费 `read_events()` 结果；若恢复账或保存账尚未进入 API 读模型，返回的可见历史可能暂不完整。此限制不影响 checkpoint 恢复。

## 六、客户端生命周期、部署配置

- 使用 Python SDK v4 `Langfuse` 客户端；只读 `LANGFUSE_*` 配置，不把密钥记入事件 metadata / content / 日志。
- `LANGFUSE_BASE_URL` 必须是本机 self-hosted URL；生产装配显式选 `backend="langfuse"`。客户端调用 `flush()` / `shutdown()` 的生命周期由 `TraceTool` 暴露的关闭入口承担，run 正常结束时 flush，进程退出时 shutdown。
- SDK `flush()` 有界等待策略及超时配置应由客户端能力支持；具体参数按所锁 SDK 版本的签名实现。flush 失败可记录 warning 并保留原始业务结果；读取错误仍向调用者抛出。
- API 查询每次带 `traceId` 与有界时间范围，并按 cursor 分页；范围起点取 API 允许的最早有效时间（同一 run 恢复后是新进程新实例，拿本实例构造时刻当下界会把上一实例写的 `checkpoint_save` 与历史 observation 全部挡在门外），数据集由 traceId 限定。
- 服务部署、项目初始化、公私钥创建与数据库卷备份由本机 Langfuse Compose 文档负责，不由本模块自动执行。

## 七、构造接口与选择

`LangfuseTrace(trace_id, *, client=None)` 实现 `TracePort`：`trace_id` 由调用方（tool 层）用 `client.create_trace_id(seed=run_id)` 造好递进来，本模块对 `run_id` / `branch` 零持有（二者只作为 meta 的键随账进来）。`client` 仅供契约测试注入，生产默认由 Langfuse SDK 按配置构造。trace ID 和事件序列基线是实例状态；不增加模块级可变单例。

`TraceTool.build(..., backend="local")` 保持兼容：

- `local`：当前 `LocalTrace` 行为不变；
- `langfuse`：构造 `LangfuseTrace`，必须配置本机 SDK 凭据 / base URL；不自动 fallback；
- 未知 backend：装配时显式 `ValueError`。

Langfuse backend 与 `live_feed_url` 可以组合：先把 trace observation 送 Langfuse，再将同一项目事件送现有人在环 feed；两边都不能成为恢复状态来源。

## 八、验证清单

- `LangfuseTrace` 结构满足 `TracePort`，不 import项目其他模块；离线测试通过注入 SDK client 检查 observation 创建参数和查询转换。
- 至少覆盖 append 返回本地 UUID、meta 盖章、确定性 trace ID、模型账 generation 类型、精确筛选和排序、API 分页、API 延迟/缺父 checkpoint observation、SDK flush / shutdown、Langfuse 不可用时 checkpoint 恢复不受影响。
- 使用本机自托管 Langfuse v4 做 smoke：一个 run、一个 episode/task/step、一个 generation、一个 checkpoint save + restore branch；确认 Dashboard 树、API 解码与 UUID 回链。
- `LocalTrace` 现有测试继续验证本地后端兼容。实现尚未通过本机服务 smoke 前，不将真实 run 默认切到 Langfuse；切换经 `backend` 参数显式开启。

## 九、官方技术依据

- [Python SDK 概览](https://langfuse.com/docs/observability/sdk/overview)：SDK v4、self-hosted 配置、observation 与异步发送。
- [Python SDK instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation)：`start_as_current_observation`、显式 trace context、trace ID、flush / shutdown。
- [Observations API](https://langfuse.com/docs/api-and-data-platform/features/observations-api)：Langfuse v4 observation 查询、分页与可见性。
- [Trace IDs & Distributed Tracing](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing)：稳定 trace ID 和 parent span context。
