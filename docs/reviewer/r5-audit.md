# R5 前置核查

基线：`5e00f47`；分支：`codex/reviewer-r5`；编号：518。仅使用隔离临时目录与确定性
embedding / reranker 替身，未接真实模型、未改生产记忆。

## 结论与用户裁决

现有 recall 不满足原定“任何入参下都不改记忆”的磁盘零写入保证。用户在核查后明确答复：
“算是客观更新没有任何问题，可以更新”。据此保留现有 recall 的索引与向量缓存刷新行为，
不新增纯查询接口、不扩展 memory / MCP 能力面。R5 的只读保证限定为无业务写操作：
查询不写 trace、不改写记忆记录正文、不调用 memorize；派生缓存允许正常刷新。

实现通过只声明 read_events / recall 的窄 Protocol 注入依赖，实际 MCP 测试验证
记录正文哈希不变，同时确认索引与向量缓存可正常更新。该保证不再等同于磁盘零写入。

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
- Langfuse 读取器绑定构造时的 trace_id，实际寻址为 `(run_id, branch)`。R6b 已在独立
  入口采用 Observations API 跨 trace 分页、解码兼容封套后按完整 meta 等值筛选，避免
  固定 main 分支导致恢复分支漏账。不改 trace 能力；这会扫描项目候选页，数据量大时
  查询可能更慢。本次使用 SDK 契约替身验证跨页、跨 run 与跨 branch，未连接真实 Langfuse。

## 4. 实现时必须遵守的当前形状

- TraceEvent 已使用双时刻和 seq，当前排序契约是 `(ended_at, seq)`；spec §五中的
  `(ts, uuid)` 已陈旧，应在 R5 落地时同步说明，不新增第二套排序源。
- `render_events` 位于 harness，reviewer 除装配入口外只能依赖 schemas 和第三方库，
  因此应复用其行格式而非 import harness 实现。
- `BrainFramesQuery` 的模型可在 R5 定义，实际回答仍归 R6a hub，不经 ViewReaders。

探针原始结果位于本 worktree `.pytest_tmp/r5-audit/report.json`（不入 Git）。
