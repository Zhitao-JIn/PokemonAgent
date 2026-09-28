# plan —— LangfuseTrace 实现与切换

> 流程位置：`langfuse-intent.md` → `langfuse-spec.md` → **langfuse-plan.md** → implementation
> 状态：P0–P3 已实现；P4 已完成（fake 测试全绿、全量 pytest 通过、真机 smoke 22/22、
> mock+真三张图 rehearsal 通过，0927）。**待用户确认服务稳定后，讨论是否把 Langfuse
> 设为真实 Harness 默认 backend**（执行约束最后一条）。
> 基于：`docs/eval/langfuse-spec.md`（2026-09-27）

---

## 目标

实现 `LangfuseTrace` 并使它可通过现有 `TraceToolPort` 使用。本机自托管 Langfuse 是唯一 trace 持久层；不双写 `LocalTrace`，不建立本地 trace 事件 outbox。SDK 追加异步、API 查询最终一致；checkpoint 状态恢复不依赖 trace 可见性。

## 阶段与交付

### P0：固定 SDK 配置与最小依赖（已完成）

- 在 `pyproject.toml` 声明 Langfuse Python SDK v4 运行依赖（`>=4.7,<5`），以支持当前 OpenTelemetry instrumentation 与 self-hosted Langfuse v4 Observations API v2。
- 配置入口只读取 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`；错误配置在选择 Langfuse backend 时显式失败，不回退到 `LocalTrace`。
- 不在源码、trace metadata 或 changelog 写密钥；缺配置时的验证使用注入的 fake client。

**完成判据**：SDK 构造与确定性 `trace_id` 生成位置明确；默认 LocalTrace 装配行为不变。

### P1：实现 TracePort 编码与 Langfuse 写入（代码已完成，未测试）

- 新增 `pokemon_agent/trace/langfuse_trace.py`，结构满足 `TracePort`；SDK import/构造延迟到 Langfuse backend 使用时，保证默认本地路径不强制初始化 SDK。
- `TracePort` 显式提供 `flush()` / `shutdown()` 生命周期方法；LocalTrace 实现为空操作，LiveFeedTrace 委托给内部 backend。
- 每条 observation metadata 保存可逆的项目事件封套：本地 UUID、kind、type、ts、完整 meta 与 content；`append()` 返回本地 UUID，绝不复用 SDK observation ID。
- `run_id` 经 SDK `create_trace_id(seed=run_id)` 稳定映射；追加 observation 显式设置 trace context 和 parent observation ID。
- `model_call` 作为 generation；其他项目事件使用 span。metadata/content 保持原样，便于既有 parse、评测、血缘代码消费。
- 在 `run_end` / `run_error` 等运行边界 flush；客户端 shutdown 使用 SDK 生命周期管理。

**完成判据**：注入 fake client 时可检查事件字段、trace context、observation 类型、metadata 和 UUID 返回值；运行不需要启动 Langfuse 服务。

### P2：实现 API 读取、过滤、分页与恢复分支树（代码已完成，未测试）

- `read_events(meta)` 经 `client.api.observations.get_many(trace_id=..., fields=..., limit=..., cursor=...)` 读取当前 run 的 observations，跳过无项目封套的外部 observation。
- 解码封套后应用 AND 等值 meta 筛选，按 `(ts, uuid)` 升序返回；所有分页完成后再返回。查询错误向上传播，不伪装成空列表。
- 将 episode/task/step scope 映射为 Langfuse parent observation；保存 scope observation ID 只存在于当前 adapter 实例，不作为 checkpoint 状态。step scope 按步建立，步内的多个操作账会共享该父节点。
- `checkpoint_restore` 依据 `checkpoint_id` 查询相同 trace 中 `checkpoint_save` 的 observation，将恢复 branch 挂在保存点下。若父 observation 尚未可查，branch 挂 run root 并携带待解析 lineage metadata；不阻塞或回滚恢复。
- 确认现有 `TraceTool.read_events()` 血缘拼接在 Langfuse 最终一致的读模型下能按 spec 工作；checkpoint 状态恢复代码不读 Langfuse。

**完成判据**：fake API 覆盖分页、多 run 隔离、meta 交集筛选、排序、未知 observation 跳过、父 checkpoint 缺席及最终出现后的查询结果。

### P3：接入 tool 工厂与应用装配（代码已完成，未测试）

- 更新 `TraceTool.build()` 接收 `backend` 与 Langfuse 配置字段；`local` 保持现有默认行为，`langfuse` 明确构造 `LangfuseTrace`，未知值报 `ValueError`。
- 在 `pokemon_agent/build.py::build_real()` 暴露 `trace_backend` 选择，并原样交给 `TraceTool.build()`；装配点仍不 import `pokemon_agent.trace` 的实现。
- 保留 `live_feed_url` 组合语义：Langfuse 先记录，现有 `LiveFeedTrace` 再向人在环 feed 转发同一事件。
- 更新 trace 包出口、trace SPEC/API、Langfuse spec/intent 与使用配置说明；只在 tool 层处理 TraceEvent 与 Langfuse observation 形状转换。

**完成判据**：默认调用不需要 Langfuse 配置；显式 `trace_backend="langfuse"` 时验证配置错误信息清楚，且不会静默写进本地 JSON。

### P4：自动化验证与本机服务 smoke（待执行）

- 新增 `tests/test_langfuse_trace.py`，以注入的 fake client/API 测试 `TracePort` 读写、ID、父子关系、分页和延迟行为；不在单元测试中连网。
- 更新 `tests/test_trace_tool.py` / `tests/test_build.py` 中必要的工厂选择示范，确认 LocalTrace 现有行为无回归。
- 运行相关测试，再运行全量 pytest 与 `ruff check .`；记录确切结果到 CHANGELOG。
- （尚未执行）使用本机 self-hosted Langfuse v4 做一次不启动 ROM、不调模型的 smoke：写入 run root、episode/task/step、generation、checkpoint save/restore；flush 后等待 Observations API 可见，再检查事件还原、branch 父节点和 Dashboard 树。
- 若本机服务未运行或 SDK 凭据未配置，只完成 fake client 阶段并明确标注 smoke 未跑；不连接 Langfuse Cloud，不启动真实游戏 Harness。

**完成判据**：自动测试通过；本机 smoke 若环境具备则通过；否则 `trace_backend` 仍显式 opt-in，不能把未验证的服务路径设为真实 Harness 默认值。

## 预期文件范围

- 新增：`pokemon_agent/trace/langfuse_trace.py`、`pokemon_agent/trace/langfuse_support.py`、`docs/eval/langfuse-plan.md`。
- 修改：`pokemon_agent/trace/__init__.py`、`pokemon_agent/tools/trace/__init__.py`、`pokemon_agent/build.py`、`pyproject.toml`、trace API/SPEC、`docs/eval/langfuse-{intent,spec}.md`、`CHANGELOG.md`。
- 不修改：checkpoint manifest / restore 逻辑、世界存档、模型 provider、Langfuse Compose 部署文件、现有机械 scorer 的判据。

## 风险与处理

| 风险 | 处理 |
|---|---|
| SDK flush 后 API 仍未立刻可读 | 接受最终一致性；API 读侧可暂时缺少新事件，运行边界 flush 后再查询。 |
| checkpoint save observation 尚不可查 | 新 branch 先挂 run root，保留 `checkpoint_id` / parent branch metadata；恢复照常完成。 |
| SDK 自身队列在强制退出时未发出 | 明确记录为唯一存储的可用性边界；不伪称有本地 durable outbox。 |
| 把大体量模型内容写入 metadata | 事件封套按 Langfuse 字段大小约束验证；如需拆分或截断，必须另行评估 TracePort 无损读取要求，不能静默丢字段。 |
| Langfuse v3 self-host 与 API v2 不兼容 | 配置检查与部署说明要求 v4；不自动探测后降级到 LocalTrace。 |

## 执行约束

- 每个 P 阶段完成后同步更新 CHANGELOG，遵照“一条编号条目对应一个 commit”的项目规则。
- 只有 P4 本机 smoke 通过并由用户确认服务运行稳定后，才讨论是否把 Langfuse backend 设为真实 Harness 默认；本计划本身不授权连接 Cloud。
- 本计划不启动 `check_harness` 或其他真机运行；需要 ROM/PyBoy/真实模型的核对由用户决定并亲自启动。
