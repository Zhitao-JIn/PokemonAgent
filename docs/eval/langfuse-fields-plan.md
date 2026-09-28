# plan —— Langfuse 字段适配实现（environment / version / input / 双时刻）

> 流程位置：`langfuse-intent.md`（上轮）→ `langfuse-fields-spec.md` → **本文件** → implementation
> 状态：**P0–P4 已落码，P5 自动化验证完成**（定向 + 全量 pytest 252 全绿、ruff 干净、
> `test_screen_text` 缺 pyboy 为沙箱环境性失败除外；CHANGELOG 312）。**待执行：本机
> smoke / rehearsal 真机核对**（需 Docker Langfuse 服务，与上轮同为用户本机操作）。
> 基于：`docs/eval/langfuse-fields-spec.md`（2026-09-27，含 22:10/22:18 两次用户修订）。
> 上轮管线见 `langfuse-plan.md`（P0–P4 已完成，Langfuse 已是默认 backend）。

---

## 目标

在不破坏无损封套与既有读侧契约的前提下：给 Langfuse 落库账补上 environment / version
标注；input 按"请求面"三分投影、六条 RAG 读口改 retriever 类型；封套时间从 append 时刻
的单值 `ts` 改为操作真实起止 `started_at` / `ended_at` 双时刻，全部排序与血缘切分改用
`ended_at`。改动横跨 trace / tool / brain / harness 四层，但 brain 只加"写进 payload
的两个只读字段"，无状态铁律与模块边界零触碰。

## 阶段与交付

### P0：environment / version 常量与透传

- `langfuse_support.py` 定义 `LANGFUSE_ENVIRONMENT_NAME = "local"`、
  `LANGFUSE_ADAPTER_VERSION = "0.1.0"`；`build_client_from_environment()` 构造时传
  `environment=…`。
- `LangfuseClientPort` 的 `start_as_current_observation` / `start_observation` /
  `create_event` 补 `version` 形参；核对 SDK `create_event` 真实签名——不收 version
  则错误账改走 `start_observation(as_type="event", version=…)`（决定写进 CHANGELOG）。
- `langfuse_trace.append` 逐账传 version；scope 锚（branch/run/episode/step，含 fake）
  统一带；`tests/_fake_langfuse.py` Fake client 收 version 并可断言。

**完成判据**：注入 fake client 的测试断言每笔 observation 带 `version="0.1.0"`；
client 构造参数带 `environment="local"`；不连网。

### P1：input 三分 + retriever 类型

- `langfuse_support.py` 新增 `retrieve_input_fields(content)`（投 `query`，缺键退空，
  与 `generation_input_fields` 同款口径）。
- `langfuse_trace.append`：input 由"一律 `{local_event_uuid}` 占位"改三分——
  `type == "model_call"` 保持 `generation_input_fields`；`kind` ∈ 五条 READ_*（经
  `retrieve_node` 渲染的 MEMORY_IO 账）投 query 且 `as_type="retriever"`；其余 `None`。
  判定不逐 kind 硬编码：以"渲染层已知的请求面"为准，kind 清单收在
  `langfuse_support.py` 一个常量里（与 `MODEL_CALL_KINDS` 同风格，测试各钉一条）。
- `tests/test_langfuse_trace.py` 补三分断言；smoke 相应更新。

**完成判据**：fake 测试覆盖三类各至少一账：generation input=prompt/images、
读口 input={"query": …} 且 as_type=retriever、机械账 input 为空；读侧
`decode_observation_event` 不受影响（只读 output）。

### P2：封套双时刻改造（本计划最宽的一刀）

- `new_event_envelope` 签名改 `(uuid, kind, type, started_at, ended_at, meta, content)`；
  两时刻 wall clock float。`schema_version` 5→6（`store.py` / `datastore/event.py`
  两份副本同步）。
- `Event`（trace/interface）、`ParsedEvent`（tools/trace/parse）、`Fork`
  （tools/trace/lineage）字段 `ts` → 按读方最小需要改名（排序/比较只用 `ended_at`
  的场合只留 `ended_at`；两处都用的带全）。
- `Rendered` 加可选 `started_at` / `ended_at`；`TraceTool.append` 组封套时优先取
  Rendered 的值、缺省补 `start = end = time.time()`。
- `langfuse_trace.append`：删 `_next_timestamp()` 与 `_last_ts`；
  `LocalTrace.append` 同步（`store.py:162` 的 now 双用为起止缺省）。
- `decode_observation_event` 读新键；旧账（无新键）解码失败被过滤，接受断代。

**完成判据**：全量 pytest 里与 trace 相关的测试在 fake 侧全绿；封套里不再出现
`ts` 键（grep 兜底）；离线 LocalTrace 路径同样走双时刻。

### P3：真实计时落点

- `brain/brain.py` 12 处 `ModelCall(payload=…)` 组账点：provider `complete()` 前后
  取 `time.time()`，payload 加 `"started_at"` / `"ended_at"`（float）；
  `ModelCall.payload` 类型放宽为 `dict[str, str | float | list[str]]`；
  顺手修 `ModelCall` docstring 过期的"延迟"文案（schemas 侧）。
- 7 个检索节点（`retrieve_act_memories` / `retrieve_global_episode_memory` /
  `retrieve_knowledge_semantic_memory` / `retrieve_object_semantic_memory` /
  `retrieve_task_memories` / `read_plan_context`×2）：MemoryTool 查询前后取时 →
  req 新可选字段 `started_at` / `ended_at: float | None = None`。
- `tools/trace/render.py`：`model_call` 从 payload 提升双时刻到 Rendered（payload
  缺键——如 mock 路径——退 None，不补造）；`retrieve_node` 从 req 透传；其余
  renderer 不动（缺省语义归 tool 层补 now）。

**完成判据**：模型账正文与封套双时刻一致且 `started_at < ended_at`；检索账同；
机械账双时刻相等；brain 无新增实例变量、无状态铁律测试不破。

### P4：排序与血缘切换

- 六处 `(ts, uuid)` 排序/比较点改 `(ended_at, uuid)`：`langfuse_trace.read_events`、
  `store.py:222`、`lineage.py:76/85/95`（fork 时刻 = checkpoint_save 的 `ended_at`）、
  `tools/trace/__init__.py:307/310`（恢复线切分边界）、相关测试与 smoke/rehearsal
  断言。
- `langfuse_trace.append` 删 `run_end`/`run_error` 前的 `time.sleep(0.003)`
  （22:18 修订：排序权威在封套，OTEL UI 兄弟序不再补偿）。

**完成判据**：`grep -rn "\.ts\b\|\"ts\"" pokemon_agent tools scripts tests` 对封套
时间字段的引用清零（live_feed 等同名无关字段除外，逐一确认）；恢复线回放/血缘
测试全绿。

### P5：自动化验证与本机核对

- 定向测试（trace / tools.trace / brain / harness 检索节点）→ 全量 pytest（显式
  全新 `--basetemp`）→ `ruff check .`。
- 更新 `scripts/langfuse_smoke.py`（input 三分、version、双时刻有序、retriever
  类型断言）与 `scripts/langfuse_tree_rehearsal.py`（排序核对改封套 `ended_at`，
  不再要求 OTEL 侧 run_end 严格最晚）。
- Docker 服务在跑的前提下跑 smoke + rehearsal；CHANGELOG 一条编号条目收全轮
  （含 sleep 删除与旧账断代的决定）。

**完成判据**：smoke 全过；rehearsal 三条线树形核对以封套为准通过；UI 可见
environment=`local`、version=`0.1.0`、retriever 图标。

## 预期文件范围

- 新增：`docs/eval/langfuse-fields-plan.md`（本文件）。
- 修改：`trace/langfuse_support.py`、`trace/langfuse_trace.py`、`trace/store.py`、
  `trace/datastore/event.py`、`trace/interface/event.py`、`brain/brain.py`、
  `brain/interface/domain/model_call.py` 或 `schemas/harness/communication/ModelCall.py`
  （payload 类型 + docstring，以实现归属为准）、
  `schemas/harness/communication/FromHarnessToTraceToolAppendReq.py`、
  `tools/trace/render.py`、`tools/trace/parse.py`、`tools/trace/lineage.py`、
  `tools/trace/__init__.py`、harness 7 个检索节点、`tests/_fake_langfuse.py` 及相关
  测试、`scripts/langfuse_smoke.py`、`scripts/langfuse_tree_rehearsal.py`、
  `CHANGELOG.md`。
- 不修改：封套其余键与 meta 盖章口径、checkpoint manifest/restore 逻辑、模型
  provider 网络行为、`docs/eval/langfuse-{intent,spec,plan,test-*}.md`（上轮文档不回改）。

## 风险与处理

| 风险 | 处理 |
|---|---|
| `create_event` 不收 version（SDK 签名未核到） | 错误账改走 `start_observation(as_type="event", version=…)`；再不行接受错误账缺 version，CHANGELOG 记录取舍 |
| brain.py 12 处组账点形态不一（成功/异常两分支各自组账） | 逐处核对，异常分支的 ended_at 取异常抛出前最后一刻；漏记处缺省退 tool 层补 now，不补造假精度 |
| mock/离线路径没有真实耗时（FakeLLM 瞬回） | 双时刻仍记录（近似相等），不特殊处理；断言用区间不用精确值 |
| 旧 Langfuse 账解码失败被过滤 | 接受断代（服务 0927 才启用，真源在本地归档）；CHANGELOG 明示 |
| payload 键与正文键同名提升造成二义 | 提升只发生在 `render.model_call` 一处；封套双时刻是唯一排序真源，正文键仅随封套透传 |
| 排序键切换影响恢复线切分边界语义 | fork 边界从"save 账的 append 时刻"变"save 账操作结束时刻"——两者相差毫秒级，且 ended_at 语义更准；回放测试兜底 |

## 执行约束

- 每个 P 阶段完成后定向测试必须绿才进下一阶段；CHANGELOG 按项目规则在收尾统一
  落一条编号条目（对应实现 commit 组）。
- pytest 一律显式全新 `--basetemp`（用户级 memory 规则）；AI 不清大残留目录。
- 本计划不启动 `check_harness` 或任何真机运行；Docker Langfuse 服务与真机核对
  由用户本机决定并执行。
- brain 与 memory 零行为变更；若实现中发现必须触碰模块边界，停下回报，不打补丁绕过。
