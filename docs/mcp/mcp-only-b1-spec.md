# spec —— 批 ①：memory 只保留 MCP 形态

> 流程位置：intent（`docs/mcp/mcp-only-intent.md`）→ **spec（本文，v3）** → 派发 → 验收 → 合入
> 分支：`refactor/mcp-only`，基线 `352af88`，`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 范围：只做 memory 的生产代码与相关测试。world（批②）与评测脚本（批③）不动。

---

## 一、要达到的状态

1. `MemoryTool` 没有"自己造 `MemoryCapability`"的路径：生产里它只包一层 `MemoryMcpTool`。
2. `MemoryTool.build(...)` 必须拿到 server 地址；`build_real` 在装配期没有地址就报错，不进 run。
3. 进程内回退、两个本地 provider 的 import、`_from_delegate` 全部删除。
4. 测试里需要记忆的地方：harness 类默认用手写替身（但依赖真实存储契约的，如 `test_episode_memory_chapter.py`，见第三节，同样用共用夹具）；要真实记忆行为的用例，**真起一个 memory server**（用现有 `remote` 夹具的做法：真 FastMCP server + 真 `MemoryCapability`，传输走内存，不占端口），经 `MemoryTool` 访问；直接测存储 / 能力本身的用例以 `MemoryCapability` 为被测对象。parity 测试退役。

## 二、决定表

**D1 `MemoryTool` 的形状。** 构造改为 `MemoryTool(client: MemoryMcpTool)`，类型就是具体的 `MemoryMcpTool`，不引入 Protocol，不接受别的实现。删除 `_from_delegate`。测试要真实记忆行为时不再绕开 MCP，而是真起 server 再连（见 D7）。

**D2 `MemoryTool.build`。** 签名 `build(*, memory_server_url: str, memory_root: str | Path | None = None)`。`memory_server_url` 必填且非空（空串 → `ValueError`，文案指向 `MCP_MEMORY_SERVER_URL`）；`memory_root` 的含义不变，只作客户端快照目录。其余行为（造 `McpClient`、`start()`、不探活）保持。

**D3 `build_real` 缺地址即报错。** 取地址的顺序不变（显式参数 > env `MCP_MEMORY_SERVER_URL`）。取不到 → 抛 `McpTransportError`（`mcpclient/client.py` 已有），文案说明"memory 只经 MCP：设 `MCP_MEMORY_SERVER_URL` 或传 `memory_server_url`，并先起 memory server"。有地址 → 照旧打 `/health`。删掉"走进程内实现"的日志分支与相关注释。

**D4 删除项。** `memory_local.py` 里 `from pokemon_agent.memory import …`、`MemoryCapability` 的构造、`LocalEmbeddingProvider` / `LocalRerankerProvider` 的引用；`__init__` 的 provider 参数；模块 docstring 里"进程内本类直调 / 两模式共用"的措辞改为单一形态。`memory/recall.py::MemoryCapability` 本体**不动**（它是 server 的实现）。

**D7 共用的 server 测试夹具。** 把 `test_memory_admin_parity.py` 里的 `remote` 夹具（`FastMCP` + `MemoryCapability` + 内存传输的 `InMemoryClient` + `MemoryMcpTool`）提取为共用夹具，放 `tests/_doubles/memory_server.py`，提供一个上下文管理器：给记忆根、客户端快照根、是否开管理面，产出 `(capability, tool)`，其中 `tool = MemoryTool(MemoryMcpTool(...))`。用到它的测试不得再自己 monkeypatch `memory_server` 的模块级状态。注意 `memory_server` 的模块级全局（`mcp`、`_capability`、`_admin_enabled`）是共享的，用这个夹具的测试不能并行。

**D5 文件名。** `memory_local.py` 的名字现在不准确，但改名会牵动全仓 import，本批**不改名**，列为遗留项由用户另行决定。

**D6 文档。** 改掉仍说"双轨 / 缺省进程内"的现行文档：`docs/spec/tools/SPEC.md:125`、`docs/spec/mcp/SPEC.md` 里相关句、`docs/spec/build/SPEC.md`、`AGENTS.md` / `CLAUDE.md` 目录树里的 `memory_server_url=?`（**这两个文件的规范性内容不动，只改这一处事实性写法；执行方若觉得需要改别处，停下问**）。`docs/mcp/memory-admin-intent.md` 与 `memory-admin-spec.md` 是历史文档，不改。`CHANGELOG.md` 与 `changelog/` 里的历史不改。

## 三、测试处理（逐个，不按种类笼统处理）

| 文件 | 现状 | 处理 |
|---|---|---|
| `tests/mcpclient/memory_tool/test_memory_admin_parity.py` | 同一组操作在进程内与 MCP 两条路径上比对 | **退役**。其中只验证 MCP 路径的断言若有独有价值（快照跨根传递），迁进 `test_memory_admin_validation.py` 或 `tests/mcp_servers/` 已有的 in-memory transport 用例里，不重复造；迁不动就记入报告，不强行保留 |
| `tests/mcpclient/memory_tool/test_memory_admin_validation.py` | 前半用 `MemoryTool(Embedder, Reranker, …)`；后半测 `build(memory_server_url=…)` | 前半改用共用夹具（D7）；后半保持，因 D2 签名变化而调整 |
| `tests/mcpclient/memory_tool/test_episode_summary_order.py`、`test_object_recall_content.py` | 真 `MemoryTool` 测召回顺序 / 内容 | 改用共用夹具（D7）经 `MemoryTool` 访问，断言不动。`test_object_recall_content.py` 里的"两种传输"参数化删去进程内那一支，保留 MCP 那一支 |
| `tests/memory/test_memory_store.py` | `MemoryTool` 与 `LocalMemoryStore` 混测 | 逐个判断：经 Port 信封收发的用例（`tool.recall(Req)` 等）改用共用夹具（D7）；测落盘根、目录布局、缺省根的用例，被测对象本来是 `MemoryCapability`，改为直接构造它；`LocalMemoryStore` 部分不动。（这个文件的重做留给测试重做主线，本批只保它绿；若超过一半的用例无法按上述两类归位，停下汇报） |
| `tests/harness/episode/test_episode_memory_chapter.py` | 真 `MemoryTool` + 隔离目录；文件的价值正是"存储形状是真的"（"一局一条"靠按 `episode_id` 召回判断，半截正文由存储层校验拒收） | **v3 裁决：整个文件改用共用夹具（D7），不用 `_Memory` 替身**——它的断言依赖真实存储契约，替身表达不了（执行方在 v2 下已按停止条件汇报）。`test_store_refuses_a_body_that_is_only_half_there` 的校验在服务端抛出，经 MCP 回到客户端时 `MemoryMcpTool` 会包成 `AssertionError("memorize failed: …")`；先核对服务端错误文本是否仍出现在这条消息里，是则只调整 `match`（若 `match` 已能命中就不动）；不在，则把这一条迁到 `tests/memory/` 下直接对 `MemoryCapability` 测（断言内容不变），并在报告里说明 |
| `tests/budget/test_run_config.py`、`tests/evals/agent_short_goal_run/test_budget_wiring.py` | `monkeypatch(MemoryTool, "build", …)` | 签名变了但 monkeypatch 用 `**kwargs`，预计不用改；若 `build_real` 的缺地址报错让它们失败，在测试里补 `memory_server_url="http://example"`（不碰真实网络，`build` 已被替换） |

**新增用例（名即一句话说明）**

- `test_build_requires_a_server_url`：`MemoryTool.build(memory_server_url="")` 抛 `ValueError`。
- `test_build_real_without_memory_url_fails_at_assembly`：清掉 env、不传参数，`build_real` 抛 `McpTransportError`，文案含 `MCP_MEMORY_SERVER_URL`；在任何 run 开始前。若 `build_real` 参数太多不便直接调，用 monkeypatch 把装配点前的重依赖替成最小替身，**停下条件见第六节**。
- `test_memory_tool_round_trips_all_four_calls_through_a_real_server`：用共用夹具，对 recall / memorize / snapshot / restore 各走一遍，断言信封往返正确、快照落在客户端快照根。

## 四、允许改动的文件

生产：`pokemon_agent/build.py`、`pokemon_agent/mcpclient/memory_local.py`。
测试：第三节表中列出的文件，共用夹具 `tests/_doubles/memory_server.py`，及新增用例所在的 `tests/mcpclient/memory_tool/` 下新文件。
文档：D6 列出的几处；`docs/mcp/mcp-only-intent.md`（由设计侧提交，执行方不改）；`CHANGELOG.md`（四段，+10 行左右，编号由设计侧在派发时给）。
其他文件一律不动。

## 五、验证

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 全绿；沙箱特有的两个 `test_evals_script_timeout.py` 失败除外（用户本机通过）。
- 搜索：`MemoryTool(` 的非测试构造点只剩 `build` 内部；`LocalEmbeddingProvider`、`LocalRerankerProvider` 在 `mcpclient/` 与 `build.py` 里零出现。
- 破坏验证：把 `build_real` 里的缺地址报错临时删掉，`test_build_real_without_memory_url_fails_at_assembly` 必须失败；恢复后转绿。
- 汇报实测 `state_schema_hash`，应为 `4f1cac6fcc7216d5`。

## 六、停止条件

- 需要改第四节之外的文件；共用夹具无法让现有 MCP 用例（`tests/mcp_servers/`）保持绿；`HEAD` 与交接不符；起点不是全绿。
- 发现 `build_real` 缺地址的新用例无法在不连网、不起 server 的前提下写出来。
- 需要新增 `MemoryStorePort` 方法、改 `MemoryCapability` 行为，或改 `CLAUDE.md` / `AGENTS.md` 的规范性内容。
- 发现生产里还有别处构造本地 `MemoryCapability`（除 `mcp_servers/memory_server.py` 外）。

## 七、非目标

world（批②）、评测脚本（批③）、`memory_local.py` 改名、`delete_many` 是否删除、测试重做本身。

## 八、待用户确认

- **Q1** 缺地址时抛 `McpTransportError`，是否可以（备选：`ValueError`）？
- **Q2** ~~delegate 构造~~：已按用户意见改为"测试真起 server"（D1 / D7），无需再确认。
- **Q3** `memory_local.py` 暂不改名，可以吗？
