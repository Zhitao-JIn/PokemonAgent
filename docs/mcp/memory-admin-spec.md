# spec —— memory MCP 服务补齐 snapshot / restore

> 关联：`memory-admin-intent.md`
> 状态：**v1，待确认后执行**
> 范围：`mcp_servers/memory_server.py`、`mcpclient/memory_tool.py`、`mcpclient/memory_local.py`（装配）、`mcp_servers/common.py`（常量）及对应测试与文档。
> 与"删除视觉感知档"互不依赖；两项的提交不交叉。

---

## 一、契约（以进程内实现为准）

两种实现对 `MemoryCapability` 的运维口必须表现一致：

| 方法 | 契约 |
|---|---|
| `snapshot(name) -> Path` | 前置：`name` 非空、不含路径分隔符。后置：返回的 zip 已存在于**调用方一侧**的 `<memory_root>/snapshots/<name>.zip`；同名覆盖；zip 内只有 `<kind>/<file>` 条目，不含 `snapshots/`。 |
| `restore(archive) -> int` | 前置：`archive` 是调用方一侧存在的文件，可以是任意路径下的 zip。后置：服务端记忆库以 zip 为准（zip 有的覆盖，zip 没有的记录文件删除），内存态重读、单调缓存清空；返回解出的文件数。 |

Port 信封（`FromHarnessToMemoryTool{Snapshot,Restore}MemoryReq/Resp`）**不改**：`archive` 字段的含义始终是"调用方一侧的本地路径"。

## 二、决定（D1–D8）

| # | 决定 |
|---|---|
| D1 | 服务端新增两个 tool：`snapshot_memory(name)`、`restore_memory(archive_base64, sha256)`。仍用统一返回信封，错误一律 `fail("rejected", …)`。 |
| D2 | **传输内容而非路径。** `snapshot_memory` 在服务端按现有逻辑打包（落在服务端 `<root>/snapshots/<name>.zip`，保留，行为与进程内一致），再把 zip 字节 base64 后连同 `sha256`、`size` 返回：`data = {"name", "archive_base64", "sha256", "size"}`。`restore_memory` 收到 base64 与 `sha256`，校验一致后写入服务端**根目录之外**的临时文件，调用 `capability.restore(临时文件)`，无论成败都删除临时文件，返回 `data = {"unpacked": n}`。 |
| D3 | **客户端落盘位置**：`MemoryMcpTool` 增加构造参数 `snapshot_root`（`Path`），快照写到 `snapshot_root / "snapshots" / f"{name}.zip"`——与进程内实现同一目录结构，`harness/checkpoint` 的 `launch_relative(archive)`、`evals/agent_short_goal_run/dataset/build/pack.py` 对 `<memory_root>/snapshots` 的拷贝逻辑无需改动。写入先到临时文件再 `os.replace`，写前校验 `sha256`。 |
| D4 | **装配**：`MemoryTool.build(memory_root=…, memory_server_url=…)` 在 MCP 模式下把 `memory_root`（缺省 `Path.cwd() / "memory"`，与进程内缺省同口径）传给 `MemoryMcpTool(client, snapshot_root=…)`。此前 MCP 模式下被忽略的 `memory_root` 现在只管客户端快照目录，**不影响服务端的 `--memory-root`**。 |
| D5 | **管理面默认不暴露。** 服务端新增启动参数 `--enable-admin`；只有带它启动，`snapshot_memory`、`restore_memory` 才注册进 MCP 注册表。默认启动的注册表仍只有 `recall`、`memorize`。门面在调用前检查 `client.registry`，缺失时抛 `MemoryAdminDisabled`（新异常，继承 memory 门面现有错误基类；若无则继承 `RuntimeError`），消息写明"服务端需用 `--enable-admin` 启动"。`/health` 响应里增加 `admin: bool`。 |
| D6 | **体积上限**：`MAX_ARCHIVE_BYTES = 256 * 1024 * 1024`（原始 zip 字节）。服务端打包后超限则返回 `fail("rejected", …)`，客户端发送前超限则在本地抛错，不发请求。常量在 `mcp_servers/common.py` 与 `mcpclient/memory_tool.py` 各一份字面量，由测试钉等值（与 `HEALTH_PATH` 同款做法）。 |
| D7 | **互斥**：服务端用一把模块级 `threading.Lock`，`snapshot_memory`、`restore_memory`、`memorize` 三者共用，防止恢复期间并发写入；`recall` 不加锁。（本地单客户端使用场景下足够；多客户端协调不在本项。） |
| D8 | **校验**：服务端 `restore_memory` 在解 base64 后先验 `sha256`、再验是 zip（`zipfile.is_zipfile`），之后沿用 `MemoryStore.restore` 现有的"只认 `<kind>/<file>` 两层路径"防目录穿越逻辑，不另写一份。`name` 的校验沿用 `MemoryStore.snapshot` 的断言，服务端把 `AssertionError` 转成 `rejected`。 |

## 三、文件改动清单

### 服务端 `pokemon_agent/mcp_servers/memory_server.py`
- 新增 `_admin_enabled: bool` 与 `start(capability, *, enable_admin=False)`。
- 在 `start()` 中，`enable_admin` 为真时才用 `mcp.tool()` 注册 `snapshot_memory` / `restore_memory`（不写成模块顶层装饰器，否则默认就进注册表）。
- 新增 `--enable-admin` 参数；`/health` 加 `admin` 字段（同步 `mcp_servers/common.py::health_payload` 的签名与 `mcpclient/client.py` 的探活读取，如需）。
- 改写模块 docstring 中"运维（snapshot/restore/count）不进 MCP 面"一句：snapshot / restore 可经 `--enable-admin` 选择性开放；count 仍不开放。

### 客户端 `pokemon_agent/mcpclient/memory_tool.py`
- `MemoryMcpTool.__init__(client, *, snapshot_root: Path)`。
- 新增 `snapshot(name) -> Path`、`restore(archive) -> int`，签名与 `MemoryCapability` 同名方法一致（`MemoryTool._from_delegate` 用鸭子类型）。
- 门面里的 `assert envelope["ok"], …` 风格与现有 `recall` / `memorize` 保持一致。

### 装配 `pokemon_agent/mcpclient/memory_local.py`
- `MemoryTool.build` 在 MCP 分支传 `snapshot_root`（D4）；docstring 里"不进 MCP 面"的措辞同步。

### 常量 `pokemon_agent/mcp_servers/common.py`
- 新增 `MAX_ARCHIVE_BYTES`；`_CODES` 不新增（沿用 `rejected`）。

### 不改
`memory/store.py`、`memory/recall.py`、`harness/checkpoint/*`、`schemas/harness/communication/FromHarnessToMemoryTool*`、`evals/agent_short_goal_run/*`。

## 四、测试（本地 `tests/`，gitignore，需全绿）

1. **对照测试**（新增 `tests/test_memory_admin_parity.py`）：对"进程内 `MemoryTool`"与"经 MCP 的 `MemoryTool`"各跑同一串操作——memorize 若干条 → `snapshot_memory("a")` → 再 memorize 若干条 → `restore_memory(a)` → `recall` 与计数；两种实现的 `unpacked`、`recall` 结果、记忆根下文件集合逐项相等。
2. **跨根测试**：服务端 `--memory-root` 与客户端 `snapshot_root` 是**两个不同的临时目录**；快照落在客户端目录，服务端目录下也有一份；用客户端那份恢复成功。（证明不依赖共享路径。）
3. **任意路径恢复**：把快照拷到一个随意目录再用它恢复，成功。
4. **完整性**：篡改 `sha256`、篡改 base64、传入非 zip、zip 内含非 `<kind>/<file>` 条目（含 `../`）：均返回 `rejected` 或被现有逻辑跳过，库不被破坏（恢复前后 `recall` 不变）。
5. **上限**：构造超过 `MAX_ARCHIVE_BYTES` 的文件（可把常量用 monkeypatch 调小）→ 客户端发送前拒绝；服务端打包超限 → `rejected`。
6. **默认不暴露**：不带 `--enable-admin` 启动，`registry == ["recall", "memorize"]`；门面调用 `snapshot` / `restore` 抛 `MemoryAdminDisabled`，消息含 `--enable-admin`。带开关则注册表含四项，`/health.admin` 为真。
7. **互斥**：恢复进行中并发 `memorize` 不得交错（用慢 `restore` 的 stub 或事件同步验证）。
8. **常量等值**：`MAX_ARCHIVE_BYTES` 两处字面量相等。
9. 沿用并扩充 `tests/test_mcp_memory_e2e.py`、`tests/test_mcp_health.py`，不得因 `/health` 新字段而红。

## 五、验证（需要真实运行）

1. **实测先行**（编码前）：在现有 `memory/` 上用进程内实现拍一份快照，记录 zip 字节数、base64 后大小。再用 curl 或测试脚本对一个已启动的 memory server（临时加载同样大小的数据）测一次单次调用的耗时。**若 base64 后超过 64 MiB，或单次调用超过 60 秒（客户端超时为 120 秒），停止，报告，由设计侧决定是否改为分块传输。**
2. **端到端**（用户确认费用后）：以 MCP 模式（服务端 `--enable-admin`，设 `MCP_MEMORY_SERVER_URL`，进程需 `PYTHONUTF8=1`）跑 `agent_short_goal_run` 的 1 个样本，确认：恢复存档成功、至少一个 checkpoint 被保存、模型调用数大于 0。再选 2 个样本跑通即可，不要求十样本。
3. 同一批样本在进程内模式的结果作对照，只比较"能否恢复并跑完"，不比较分数。

## 六、提交

| 提交 | 内容 |
|---|---|
| M1 | `改：memory MCP 服务补齐 snapshot / restore（服务端、门面、装配、常量）` |
| M2 | `文档：memory MCP 管理面（SPEC、CHANGELOG、docstring）` |

文档范围：`docs/spec/tools/SPEC.md`（memory 远程门面一节）、`docs/spec/memory/API.md` 与 `PORTS.md`（凡写"不进 MCP 面"处）、`CHANGELOG.md` 新条目、`AGENTS.md` 与 `CLAUDE.md` 中相应说明（两份同步）。`docs/perceive/remove-vision-plan.md` 里关于"MCP 模式无法恢复存档"的遗留条目，在本项合入后改为"已由 `docs/mcp/memory-admin-spec.md` 解决"。

## 七、停止条件

- 第五节第 1 点的体积/耗时阈值被触发。
- `MemoryStore.restore` 现有的删除逻辑在服务端临时文件路径下表现不同（例如依赖 zip 位于 `snapshots/`）。
- 任何需要改动 Port 信封、`memory/store.py` 或 checkpoint 代码才能做成。
- FastMCP 不支持在 `start()` 里按条件注册 tool（则报告，改用两个独立的 `FastMCP` 实例或注册表过滤，由设计侧选）。
- 对照测试中两种实现出现无法用传输差异解释的行为差别。

## 八、非目标

分块传输与断点续传；`count` 等其他运维口；多客户端并发恢复；快照的压缩与增量；改变 recall/memorize 行为。
