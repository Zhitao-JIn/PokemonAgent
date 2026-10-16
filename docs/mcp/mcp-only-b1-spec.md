# spec —— 批 ①：memory 只保留 MCP 形态

> 流程位置：intent（`docs/mcp/mcp-only-intent.md`）→ **spec（本文，v1，待确认）** → 派发 → 验收 → 合入
> 分支：`refactor/mcp-only`，基线 `352af88`，`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 范围：只做 memory 的生产代码与相关测试。world（批②）与评测脚本（批③）不动。

---

## 一、要达到的状态

1. `MemoryTool` 没有"自己造 `MemoryCapability`"的路径：生产里它只包一层 `MemoryMcpTool`。
2. `MemoryTool.build(...)` 必须拿到 server 地址；`build_real` 在装配期没有地址就报错，不进 run。
3. 进程内回退、两个本地 provider 的 import、`_from_delegate` 全部删除。
4. 测试里需要记忆的地方：harness 类用手写替身；测记忆语义的用例直接以 `MemoryCapability` 为被测对象。parity 测试退役。

## 二、决定表

**D1 `MemoryTool` 的形状。** 构造改为 `MemoryTool(delegate: MemoryDelegate)`。`MemoryDelegate` 是同文件里的 `Protocol`，只有 `recall(query, conditions, limit)`、`memorize(records)`、`snapshot(name)`、`restore(archive)` 四个方法——`MemoryMcpTool` 与 `MemoryCapability` 恰好都满足。生产只会用 `MemoryMcpTool` 构造；测试可以传别的对象。删除 `_from_delegate`。

**D2 `MemoryTool.build`。** 签名 `build(*, memory_server_url: str, memory_root: str | Path | None = None)`。`memory_server_url` 必填且非空（空串 → `ValueError`，文案指向 `MCP_MEMORY_SERVER_URL`）；`memory_root` 的含义不变，只作客户端快照目录。其余行为（造 `McpClient`、`start()`、不探活）保持。

**D3 `build_real` 缺地址即报错。** 取地址的顺序不变（显式参数 > env `MCP_MEMORY_SERVER_URL`）。取不到 → 抛 `McpTransportError`（`mcpclient/client.py` 已有），文案说明"memory 只经 MCP：设 `MCP_MEMORY_SERVER_URL` 或传 `memory_server_url`，并先起 memory server"。有地址 → 照旧打 `/health`。删掉"走进程内实现"的日志分支与相关注释。

**D4 删除项。** `memory_local.py` 里 `from pokemon_agent.memory import …`、`MemoryCapability` 的构造、`LocalEmbeddingProvider` / `LocalRerankerProvider` 的引用；`__init__` 的 provider 参数；模块 docstring 里"进程内本类直调 / 两模式共用"的措辞改为单一形态。`memory/recall.py::MemoryCapability` 本体**不动**（它是 server 的实现）。

**D5 文件名。** `memory_local.py` 的名字现在不准确，但改名会牵动全仓 import，本批**不改名**，列为遗留项由用户另行决定。

**D6 文档。** 改掉仍说"双轨 / 缺省进程内"的现行文档：`docs/spec/tools/SPEC.md:125`、`docs/spec/mcp/SPEC.md` 里相关句、`docs/spec/build/SPEC.md`、`AGENTS.md` / `CLAUDE.md` 目录树里的 `memory_server_url=?`（**这两个文件的规范性内容不动，只改这一处事实性写法；执行方若觉得需要改别处，停下问**）。`docs/mcp/memory-admin-intent.md` 与 `memory-admin-spec.md` 是历史文档，不改。`CHANGELOG.md` 与 `changelog/` 里的历史不改。

## 三、测试处理（逐个，不按种类笼统处理）

| 文件 | 现状 | 处理 |
|---|---|---|
| `tests/mcpclient/memory_tool/test_memory_admin_parity.py` | 同一组操作在进程内与 MCP 两条路径上比对 | **退役**。其中只验证 MCP 路径的断言若有独有价值（快照跨根传递），迁进 `test_memory_admin_validation.py` 或 `tests/mcp_servers/` 已有的 in-memory transport 用例里，不重复造；迁不动就记入报告，不强行保留 |
| `tests/mcpclient/memory_tool/test_memory_admin_validation.py` | 前半用 `MemoryTool(Embedder, Reranker, …)`；后半测 `build(memory_server_url=…)` | 前半改为 `MemoryTool(MemoryCapability(...))`（被测对象是管理面校验，不是传输）；后半保持，因 D2 签名变化而调整 |
| `tests/mcpclient/memory_tool/test_episode_summary_order.py`、`test_object_recall_content.py` | 真 `MemoryTool` 测召回顺序 / 内容 | 被测对象实际是 `MemoryCapability` 的召回语义：改为 `MemoryTool(MemoryCapability(...))`，其余断言不动。`test_object_recall_content.py` 里的"两种传输"参数化删去进程内那一支，保留 MCP 那一支 |
| `tests/memory/test_memory_store.py` | `MemoryTool` 与 `LocalMemoryStore` 混测 | 凡 `MemoryTool(_FakeEmbedder(), _FakeReranker(), …)` 一律改为 `MemoryTool(MemoryCapability(_FakeEmbedder(), _FakeReranker(), memory_root=…))`；`LocalMemoryStore` 部分不动。（这个文件的重做留给测试重做主线，本批只保它绿） |
| `tests/harness/episode/test_episode_memory_chapter.py` | 真 `MemoryTool` + 隔离目录 | 它是 harness 测试，按用户决定改用手写替身：优先用 `tests/_harness_fixtures/memory.py` 的 `_Memory`；若它表达不了某条断言（例如要求真实落盘形状），**停下汇报**，不自己扩充替身语义 |
| `tests/budget/test_run_config.py`、`tests/evals/agent_short_goal_run/test_budget_wiring.py` | `monkeypatch(MemoryTool, "build", …)` | 签名变了但 monkeypatch 用 `**kwargs`，预计不用改；若 `build_real` 的缺地址报错让它们失败，在测试里补 `memory_server_url="http://example"`（不碰真实网络，`build` 已被替换） |

**新增用例（名即一句话说明）**

- `test_build_requires_a_server_url`：`MemoryTool.build(memory_server_url="")` 抛 `ValueError`。
- `test_build_real_without_memory_url_fails_at_assembly`：清掉 env、不传参数，`build_real` 抛 `McpTransportError`，文案含 `MCP_MEMORY_SERVER_URL`；在任何 run 开始前。若 `build_real` 参数太多不便直接调，用 monkeypatch 把装配点前的重依赖替成最小替身，**停下条件见第六节**。
- `test_memory_tool_delegates_envelopes_to_the_delegate`：用手写 delegate 记录调用，断言四个方法各转发一次且信封往返正确。

## 四、允许改动的文件

生产：`pokemon_agent/build.py`、`pokemon_agent/mcpclient/memory_local.py`。
测试：第三节表中列出的文件，及新增用例所在的 `tests/mcpclient/memory_tool/` 下新文件。
文档：D6 列出的几处；`docs/mcp/mcp-only-intent.md`（由设计侧提交，执行方不改）；`CHANGELOG.md`（四段，+10 行左右，编号由设计侧在派发时给）。
其他文件一律不动。

## 五、验证

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 全绿；沙箱特有的两个 `test_evals_script_timeout.py` 失败除外（用户本机通过）。
- 搜索：`MemoryTool(` 的非测试构造点只剩 `build` 内部；`LocalEmbeddingProvider`、`LocalRerankerProvider` 在 `mcpclient/` 与 `build.py` 里零出现。
- 破坏验证：把 `build_real` 里的缺地址报错临时删掉，`test_build_real_without_memory_url_fails_at_assembly` 必须失败；恢复后转绿。
- 汇报实测 `state_schema_hash`，应为 `4f1cac6fcc7216d5`。

## 六、停止条件

- 需要改第四节之外的文件；`HEAD` 与交接不符；起点不是全绿。
- 发现 `build_real` 缺地址的新用例无法在不连网、不起 server 的前提下写出来。
- 替身表达不了 `test_episode_memory_chapter.py` 的某条断言。
- 需要新增 `MemoryStorePort` 方法、改 `MemoryCapability` 行为，或改 `CLAUDE.md` / `AGENTS.md` 的规范性内容。
- 发现生产里还有别处构造本地 `MemoryCapability`（除 `mcp_servers/memory_server.py` 外）。

## 七、非目标

world（批②）、评测脚本（批③）、`memory_local.py` 改名、`delete_many` 是否删除、测试重做本身。

## 八、待用户确认

- **Q1** 缺地址时抛 `McpTransportError`，是否可以（备选：`ValueError`）？
- **Q2** `MemoryTool` 改成"传入 delegate"的构造，测试传 `MemoryCapability`，可以吗？（备选：生产类只留 `build`，测试用 `_from_delegate` 保留的私有口——我不推荐，会让私有口变成公共约定。）
- **Q3** `memory_local.py` 暂不改名，可以吗？
