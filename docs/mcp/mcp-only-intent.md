# intent —— memory 与 world 只保留 MCP 形态

> 流程位置：**intent.md（本文）** → spec.md → plan → 执行 → 验收 → 合入
> 状态：**v1 草案，待确认**；批 ① 的 spec 见 `mcp-only-b1-spec.md`
> 起草：2026-10-16
> 性质：生产代码改动 + 测试与评测脚本改动。**独立于**测试重做主线（`docs/test/`），分支 `refactor/mcp-only`（基线 `352af88`，已含 remove-vision 并入与 max_summaries 删除）。
> 取代：`docs/mcp/memory-admin-intent.md` 里"同一个 Port 保留两种实现、要求两种实现能力一致"的前提。该文档的结论（MCP 模式下能 snapshot/restore）继续成立，"两种实现一致"这条要求随进程内实现一起退役。

---

## 一、一句话意图

`memory` 和 `world` 在运行链路里只经 MCP 访问：装配点不再提供"没配 server 地址就进程内直连"的回退，`MemoryToolPort` 与 `GameToolPort` 各只剩一个实现（MCP 门面）。

## 二、为什么做

1. **两条路径，永远有一条没人用。** `build.py` 对 memory 和 world 都写着"给了地址走 MCP，不给走进程内（改造前的行为）"。使用者已经只走 MCP（`.env` 里配了 `MCP_MEMORY_SERVER_URL`），进程内那条是历史包袱，却要一直维护、一直测。
2. **静默回退是隐患。** 忘配地址时 run 悄悄走进程内，结果看起来正常，行为却和线上不是同一条链路（例如 world 的租约、`/health` 探活、快照经 base64 传输都不存在）。装配期直接报错比悄悄换路径安全。
3. **parity 测试是两条路径的产物。** `tests/mcpclient/memory_tool/test_memory_admin_parity.py` 的存在，就是因为要钉住两种实现不漂移。只留一种实现，这类测试和它防的缺口一起消失。
4. **测试重做因此更干净。** 马上要重做 memory 与 harness 的测试；先决定实现只有一种，再写测试，避免给要删的路径写用例。

## 三、做什么

**生产代码**
- `build.py`：memory、world 两处"未配地址 → 进程内"分支删除；未配 `MCP_MEMORY_SERVER_URL` / `MCP_WORLD_SERVER_URL`（且显式参数也没给）→ 装配期直接报错，不进 run。已有的 `/health` 探活保留。
- `mcpclient/memory_local.py`：`MemoryTool` 不再有"自己持有 `MemoryCapability`"的构造路径，只作为 `MemoryMcpTool` 之上的 Port 信封适配层；`build()` 要求给 server 地址。
- `mcpclient/game_tools.py`：`GameTools.build` 里的进程内 `PyBoyWorld` 分支删除，返回 `WorldMcpTool`。
- 保留不动：`memory/` 包（含 `MemoryCapability`）和 `world/` 包本体——它们是各自 server 的实现，不是"进程内形态"。

**测试**
- harness 层测试需要记忆与世界时，用 `tests/_doubles/` 与 `tests/_harness_fixtures/` 里的手写替身（已有 `memory.py`、`world.py`），不起 server。
- 原先用真实进程内 `MemoryTool` 的测试，逐个改成替身或直测 `MemoryCapability`（`tests/harness/episode/test_episode_memory_chapter.py`、`tests/mcpclient/memory_tool/*`、`tests/memory/test_memory_store.py` 等，清单在 spec 里逐个定）。
- parity 测试退役。
- MCP 两层（客户端门面、server 外壳）的测试用现有的 in-memory transport 方式，不依赖真实端口。

**评测脚本**
- `evals/memory_store_recall/solver.py`：改为连 memory server（地址来自 env）。
- `evals/common/world_case.py` 及其调用方（`world_script_execute`、`dataset/frames/build/freeze.py`、`terrain.py`）：改为经 world server 的 MCP 接口取帧、按键、读内存；不再直接 `new PyBoyWorld`，也不再碰私有属性 `_pyboy`。
- 评测真正跑的时候才起 server；本项的验证只做到"脚本改完、静态检查与单元测试绿"，真实评测运行另行确认。

## 四、不做什么

- 不改 `memory/` 与 `world/` 包内部逻辑，不改 recall/memorize 行为，不改 Port 信封。
- 不改 `Task` 或任何参与 `state_schema_hash` 的结构（评测存档保持可恢复）。
- 不改 checkpoint 逻辑；`--enable-admin` 的默认值也不动。
- 不删除 `pokemon_agent/memory/` 里的 `LocalMemoryStore` 等"可作为库使用"的类。
- 不在本项里做 memory / world 的测试重做；本项只是让测试重做有一个稳定的对象。

## 五、需要确认的点

1. **范围与批次。** 建议拆三批、各自可单独验收和回退：①memory 只留 MCP（生产代码 + 相关测试），②world 只留 MCP（生产代码 + 相关测试），③评测脚本改走 MCP。先①，验证做法后再②③。
2. **局摘要数量上限 `max_summaries` 已另案删除**（CHANGELOG 478，分支 `fix/drop-max-summaries`，本分支已包含）。因此 memory server 不需要为它增加启动参数，评测也不再传它。
3. **world 评测改 MCP 的可行性。** world server 已有 `step`、`load_state`、`perceive_task` 与租约，原则上够用；`world_script_execute` 评测要的"按键后读帧"如果有当前接口不覆盖的部分，在③批的 spec 里单独列出，不在 intent 里预判。

## 六、风险

- **所有只想"随手起一个单进程跑一下"的用法会失效**：本地调试也要先起两个 server。这是预期代价，spec 里要给出起 server 的命令清单。
- **评测脚本无法在隔离环境里真跑**：改完只能验证到静态与单元测试层面，真实运行要用户在本机起 server 后确认（涉及模拟器与本地 embedding 模型，不涉及付费模型调用）。
- **与进行中的工作冲突**：`feature/reviewer-transparency` 与 `perceive/remove-vision` 两条线可能碰 `build.py`、`mcpclient/game_tools.py`、`CHANGELOG.md`；合入顺序在 plan 里写。

## 七、成功的样子

- 不配 server 地址，`build_real` 在装配期立刻报出明确错误；配了地址且 `/health` 通过，行为与现在 MCP 模式完全一致。
- 全仓库搜 `PyBoyWorld(` 与进程内 `MemoryCapability(` 构造，只剩 server 入口与测试直测。
- 全量 pytest、`ruff check`、`ruff format --check` 全绿；失败集合与基线一致。
- `state_schema_hash` 仍是基线值 `4f1cac6fcc7216d5`。
