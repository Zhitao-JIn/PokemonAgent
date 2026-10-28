# spec —— 移除图内恢复与存档体系（只保留启动时按 `.state` 恢复世界）

> 流程位置：intent（用户决定，2026-10-28）→ **spec** → plan → 落码。依据：只读盘点 `experiment/checkpoint_inventory/inventory.md`（不入库）。
> 编号：691–694，每个任务一个 worktree 与分支，顺序做，做完一个合并一个。**删除目录或文件由用户做，执行方不删**（执行方环境不允许递归删除）；`uv.lock` 由用户在本机刷新。
> 与长期任务的顺序：**688 → 689 → 本 spec（691–694）→ 690**。冻结记忆种子之前必须先做完移除，因为种子里的 run 记忆与 trace 元数据会随 `branch` 等字段的收窄而变化，种子必须冻结在最终格式上。

## 一、决定（用户："不做真正的恢复"；harness 只在启动时按存档恢复世界，不做中途恢复；memory 只是指向一个新的记忆仓库）

| 编号 | 决定 |
|---|---|
| D1 | 移除 checkpointer 体系：`pokemon_agent/harness/checkpoint/` 整个包、三级存档与图内恢复、LangGraph saver、checkpoint 专属 schema、trace 的 `checkpoint_save` / `checkpoint_restore` / checkpoint 错误账、血缘 `lineage.py` 与 Langfuse 的恢复祖先锚、memory 服务的 `snapshot_memory` / `restore_memory` 管理接口与 admin 开关、对应测试与文档 |
| D2 | **保留**：启动时按 `.state` 恢复世界（world 的 reset 与 `state_base64`、`use_start_state`）、评测样本 `start` 的 `.state` 加载与哈希校验、`capture_control.py` 的评测批次重跑（它不是图状态恢复）、`_read_run_index` 读别的 run 的记忆（只依赖 recall 结果，种子目录复制进去即可） |
| D3 | `branch`：**本轮收窄为常量 `main`，不删字段**。理由：旧数据与 Langfuse 的 trace 定址仍用 `(run_id, branch)`；等旧数据不再需要时再删字段。`RunState.branch`、`run.branch` 配置项移除，trace 元数据里 `branch` 由 trace 工具恒盖 `main` |
| D4 | memory 的 store 层通用 `snapshot/restore`（zip 算法与它的安全测试）：694 里先查**非 MCP 的调用者**；没有任何非测试调用者就一并删除，有就保留并在汇报里写明谁在用。种子复制不依赖它 |
| D5 | 样本 `start.kind` 的值 `archive` 与 `archive` 字段是**历史命名**，不是 checkpoint 存档：实际数据里 `v20261021_retest5` 20 条与 `v20261028_short_frozen` 20 条的 `kind` 都是 `archive`（`archive` 字段非空，加载时被忽略），起点都是 `.state`；`v20261028_mid` 5 条是 `state`。**本轮不动**，数据格式清理另排（盘点里"40 条 archive：15 加 25"的数字有误，以此为准） |
| D6 | LangGraph saver 依赖（`langgraph-checkpoint-sqlite`）：691 里改 `pyproject.toml` 删掉；`uv.lock` 由用户在本机运行 `uv lock` 刷新，执行方不运行 uv |
| D7 | 文档：`docs/checkpoint/`（及 `docs/spec/checkpoint/` 若存在）由用户删除；`AGENTS.md`、`docs/ROADMAP.md`（H9 标取消、F5 重写）、`docs/spec/trace/*`、`docs/spec/DATAFLOW.md`、`docs/mcp/memory-admin-spec.md`、`docs/eval/*` 里的过时描述由设计侧在 694 之后统一改 |

## 二、四个任务（每个独立可验）

### 691 —— 切断运行路径与配置

做：`pokemon_agent/build.py`（删 `Checkpointer`/`build_saver` 与装配，保留三图编译）；`harness/run/run_graph.py`（`compile` 去掉 saver 参数）；`harness/run/act/__init__.py`（删恢复计划读取与 resume 分支，保留普通 `run_episode` 与错误结算）；`harness/episode/episode_entry.py`（删 `resume_episode` 与导出）；`harness/task/task_entry.py`（删存档调用）；`harness/run/run_entry.py`（删 `checkpoint_only`、run 存档、按 thread 恢复，保留每次新 run reset 世界一次）；`harness/run/harness.py`（删 `checkpoint_only` 参数）；三层 runtime 的 `Checkpointer` 字段与类型引用；`pokemon_agent/harness/checkpoint/` 包（**删除由用户做**，执行方把引用全部切断后，包变成无引用的孤岛，汇报里列出；用户删）；checkpoint 专属 schema（`CheckpointMark`、`CheckpointManifest` 等，用 `git grep` 定位，含 `schemas/harness/domain/__init__.py` 导出）；`pokemon_agent/settings/schema/deployment.py` 与 `settings/default.json` 的 `checkpoint` 节与 `paths.checkpoint`（先 `git grep` 找所有写了这些键的配置文件，一并改）；`pyproject.toml` 删 saver 依赖（D6）；checkpoint 专属测试（`tests/harness/checkpoint/` 下三个文件，共 6 个测试，其中恢复测试当前是硬 skip）由用户删除。
验收：普通 FakeWorld / FakeLLM 的整图 run 通过；`git grep -n "Checkpointer\|build_saver\|checkpoint_only\|resume_episode"` 在 `pokemon_agent/` 与 `tests/`（用户删完之后）无命中；world 的 reset 带 `state_base64` 的路径不变；tests 数减少量等于被删测试数（逐个列出）。**trace 的 `checkpoint_*` 账类型本任务保留**（留给 692），所以中间状态里它们存在但没人写。

### 692 —— 收窄 trace 协议

做：删 `TraceKind` 里的 `checkpoint_save`、`checkpoint_restore` 与 checkpoint 错误账（`schemas/harness/domain/trace_kind.py`），`direct/trace/__init__.py` 里的渲染映射，`direct/trace/render.py` 里对应渲染；删 `direct/trace/lineage.py`；`pokemon_agent/trace/langfuse_trace.py` 里恢复线的祖先锚与伪造父 span（普通层级 span 保留）；更新 node_io / 事件白名单与 trace 文档中引用这些账的位置（文档仅限 `docs/spec/trace/`，其余文档由设计侧改）；`tests/direct/trace/test_trace_branch.py` 与 Langfuse 里恢复分支的测试删除。
验收：普通 main 线 trace 写读完整（local 与 Langfuse 两个后端的现有普通用例全过）；`evals/agent_short_goal_run/scorer/stream.py` 的 `load` 在账里没有 restore 账时的行为不变（本来就退回 `main`）；`git grep -n "checkpoint_save\|checkpoint_restore\|lineage"` 在代码里无命中。

### 693 —— branch 收窄为常量 `main`，评测侧同步

做：D3：`harness/run/run_state.py`、`schemas/harness/domain/run_io.py`（`RunResult.branch` 字段**保留**，值恒为 `main`，因为 scorer 与旧数据读它）、`settings/schema/deployment.py`（删 `run.branch` 配置）、`schemas/harness/domain/trace_meta.py` 与 `direct/trace/__init__.py` 的 `_stamp_meta`（`branch` 恒盖 `main`）；评测侧：`evals/common/overlay.py` 删 `paths.checkpoint` 与 `run.branch`，`evals/agent_short_goal_run/solver/runner/one.py`、`solver/record.py` 不再持久化可变的 branch；`evals/agent_short_goal_run/scorer/stream.py` 不再扫 restore 账，local 与 Langfuse 一律按 `branch="main"` 读；Langfuse trace id 仍由 `(run_id, "main")` 决定（兼容旧数据）。
验收：同一 `run_id` 在 local 与 Langfuse 两条路径读到同样的账；现有三个数据集的样本加载与 `check` 不变；`git grep -n "run.branch\|\.branch"` 剩下的命中逐条说明（旧数据兼容）。

### 694 —— 移除 checkpoint 用的 memory 管理面

做：`pokemon_agent/mcp_servers/memory_server.py` 的 `snapshot_memory` / `restore_memory` 工具与 `--enable-admin` 开关；`pokemon_agent/mcpclient/memory_local.py`、`memory_tool.py` 里的对应方法；`schemas/harness/communication/` 里 `FromHarnessToMemoryTool*Snapshot*` 与 `*Restore*` 信封；评测里 `evals/common/eval_services.py` 与 `evals/agent_short_goal_run/solver/solver.py` 的 `admin` 参数与调用（`evals/common/memory_server.py` 的 restore 相关）；相关测试（`tests/mcp_servers/test_mcp_memory_e2e.py` 里 admin 段、`tests/mcpclient/memory_tool/test_memory_admin_validation.py`、`test_memory_mcp_only.py` 里相关用例）；D4：先查 store 层 `snapshot/restore` 的非 MCP 调用者，无则删。
验收：默认 MCP 工具列表只剩 `recall` 与 `memorize`；`eval_services` 的 `memory_seed` 与 `export_memory_to`（688）仍工作（用 688 的合成测试证明，不得改断言）；`git grep -n "snapshot_memory\|restore_memory\|enable-admin\|enable_admin"` 无命中。

## 三、通用验收与规则

- 每个任务：先取全量 pytest 基线，最终 `failures=0`、`errors=0`，`skipped=72`；`tests` 的减少量逐个列出被删测试并说明理由，**不得删除"有效但读不到数据"的测试，也不得改断言来迁就**；守卫四条 `[ OK ]`；ruff 三项；两种 `git diff --stat` 逐行一致；`CHANGELOG.md` 顶部新增对应编号条目。
- 每个任务一个 worktree 与分支，第 0 步由执行方自己 `git worktree add`（沿用 687、688 的写法），每个都从**最新 `main`** 建；做完设计侧验收提交在分支上，用户合并。
- 生产代码改动较大，设计侧验收要逐文件读 diff；遇到 spec 没预料到的引用，**停下汇报**，不自行处理。
- 不启动模拟器、不调用真实模型。
- 删除一律由用户做：每个任务的汇报里列出"需要用户删除的文件与目录"清单，设计侧给出删除命令。

## 四、用户的动作

删除清单（691、692 之后各一次，698 之前）：`pokemon_agent/harness/checkpoint/`、`tests/harness/checkpoint/`、`docs/checkpoint/`、`docs/spec/checkpoint/`（若存在）；在本机运行 `uv lock` 刷新 `uv.lock`。
