# R5 前置核查

基线：`5e00f47`；分支：`codex/reviewer-r5`；编号：518。仅使用隔离临时目录与确定性
embedding / reranker 替身，未接真实模型、未改生产记忆。完整 R5 实现尚未开始。

## 结论与待裁决

现有 recall 不满足视图“任何入参下都不改记忆”的保证。建议为 reviewer 增加显式的纯只读
查询路径，保留既有 recall 的刷新语义；这涉及 memory / MCP 的契约与实现，超出 R5 原定
仅新增 reviewer 文件的范围，须用户批准后实施。也可由用户明确放宽保证，允许查询更新
派生索引与向量缓存；该方案不能继续声称磁盘零写入。

待批准的推荐方案要求：同样的查询与 hint 语义、原记录不变、索引与向量 sidecar 不写盘、
缺失向量只在查询内临时计算；经 MCP 暴露同样的只读保证，不要求 admin 权限。
具体采用现有 recall 的显式只读参数还是独立查询方法，批准能力面变更后再确定并先写契约。

## 1. act 画面与条数：通过

- `MemoryCapability._recall_acts` 返回完整 payload，包含 before_frame / after_frame。
- 通过真实 MemoryTool → MemoryMcpTool → MCP 服务端及能力实现，使用内存传输测试，
  admin 关闭，`conditions={"episode_id": "episode"}, limit=None` 返回全部 12 条 act，
  每条两帧均保留；该次纯 hint 查询前后所有服务端文件哈希相同。
- 默认 limit 为 8，不能据此取任意步；before / after 必须显式传 None，再筛 step。
- 本次验证了 MCP 信封与服务端路径，未把内存传输称为真实网络跨进程验证。

## 2. recall 副作用：不通过，触发 spec §十八第 2 项

- `MemoryCapability._recall_episode_summaries` 与 `_recall_knowledge` 调用
  `LocalMemoryStore.refresh_changed`；外部修改 markdown 时刷新索引并追加向量。
- `LocalMemoryStore.rank` 对缺失向量调用 `_put_vector`，也会写 sidecar。
- 实测：写入一条 knowledge 后模拟外部编辑正文，再经真实 MCP recall(query="field")
  查询，命中 1 条，查询前后变化文件恰为 `knowledge_memory/index.json` 与
  `knowledge_memory/vectors.jsonl`。原记录正文未由查询改写；没有访问计数证据，
  但派生缓存写入已足以违反严格只读保证。
- 禁止以窄 Protocol 没有 memorize 方法推导底层没有写副作用。

## 3. trace flush 与可见性

- TracePort、TraceToolPort、TraceTool、LocalTrace、LangfuseTrace 已有 flush，
  不需要为 R5 新增 trace 能力。
- 本地 backend：写入一条 sense_frame，flush 后新 Python 子进程构造读取器，
  立即读到相同 uuid，跨进程验证通过。
- Langfuse：现实现明确写明 flush 只排空 SDK 队列，查询仍可能延迟；不承诺立即可见。
  本次未连接真实 Langfuse，也未改变服务配置。后续查询头行应注明可能不含最近几秒。
- Langfuse 读取器绑定构造时的 trace_id，跨 run 查询不能只换 meta 过滤；后续装配需要
  按查询 run 选择读取器，不能把固定 run 的读取器当作全局 reader。

## 4. 实现时必须遵守的当前形状

- TraceEvent 已使用双时刻和 seq，当前排序契约是 `(ended_at, seq)`；spec §五中的
  `(ts, uuid)` 已陈旧，应在 R5 落地时同步说明，不新增第二套排序源。
- `render_events` 位于 harness，reviewer 除装配入口外只能依赖 schemas 和第三方库，
  因此应复用其行格式而非 import harness 实现。
- `BrainFramesQuery` 的模型可在 R5 定义，实际回答仍归 R6a hub，不经 ViewReaders。

探针原始结果位于本 worktree `.pytest_tmp/r5-audit/report.json`（不入 Git）。
