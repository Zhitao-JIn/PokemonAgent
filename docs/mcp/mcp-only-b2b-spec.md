# spec —— 批 ②b：world 只保留 MCP 形态

> 流程位置：批 ①、②a 已合入 → **批 ②b（本文，v2）** → 批 ③（评测走 MCP）
> 分支：`refactor/mcp-only`，基线 `0ae865c`（含批 ①、②a；主工作区已快进到同一提交），`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 用户决定（2026-10-17）：`build_real` 删 `rom` / `state_file` / `watch` / `speed` 四个参数，`watch` / `speed` 改为 world server 命令行旋钮；评测在 ②b 与 ③ 之间不可用，②b 与 ③ 做完后一起合入主线。

---

## 一、事实（读码核对，基线 `0ae865c`）

- `GameTools` 除 `build()` 外，生产代码里没有构造点；唯一的构造点在批 ②a 新增的对照测试 `tests/mcpclient/world_tool/test_world_mcp_parity.py`（用 `GameTools(world)` 当"进程内基准"，第 113、168、190 行附近）。`build()` 的进程内分支只被 `build_real` 触达。删掉该分支后，整个 `GameTools` 类与 `game_tools.py::_run_script_report` 无人使用。
- `build_real(rom, state_file, watch, speed)` 这四个参数只在进程内分支有意义；MCP 模式下被静默忽略（world server 命令行只有 `--rom`、`--state-file`，没有 `watch` / `speed`）。
- 评测里 `pack.py` 给每个样本传自己的 `.state` 给 `build_real`：在 MCP 下这个起点会被**静默忽略**，打包会从 server 当时所在的状态开始，造出错误的存档——这一点必须在本批让它大声失败，而不是静默。
- `one.py` 经 `restore_run` 载入 checkpoint 里的 `world.state`（走 `load_state`），不依赖 `build_real` 的 `state_file`，在 MCP 下仍然成立。

## 二、决定表

**D1 `WorldMcpTool.build`。** 在 `mcpclient/world_tool.py` 新增 `WorldMcpTool.build(*, world_server_url: str, client_id: str | None = None) -> WorldMcpTool`，形状与 `MemoryTool.build` 同构：空串抛 `ValueError`（文案指向 `MCP_WORLD_SERVER_URL`）；否则造 `McpClient(mcp_endpoint(url))`、`start()`、返回门面；**不探活**（探活在 `build_real`，保持不变）。

**D2 删除 `GameTools`。** 删除 `pokemon_agent/mcpclient/game_tools.py`（`GameTools`、`_run_script_report`、其 `build`）。`GameToolPort`（`direct/interface`）保留，它是 harness 依赖的契约，`WorldMcpTool` 是它唯一的实现。检查 `mcpclient/__init__.py` 等出口有无再导出 `GameTools`，有则同步删。

**D3 `build_real` 的签名与行为。**
- 删除参数 `rom`、`state_file`、`watch`、`speed`，及其说明与注释（含"`watch` 与 `speed` 解耦"那段）。**注意这会改变位置参数顺序**：此前第一个位置参数是 `rom`，现在是 `text_model`。全仓所有调用点改成关键字调用或去掉被删参数，不得悄悄错位。
- `world_server_url` 取法不变（显式参数优先于 env `MCP_WORLD_SERVER_URL`）；**取不到 → 抛 `McpTransportError`**（文案：world 只经 MCP，设 `MCP_WORLD_SERVER_URL` 或传 `world_server_url`，并先起 world server），有地址照旧 `assert_mcp_server_ready(…, "world")`。world 与 memory 的缺地址检查并列，顺序为 world 在前（与现装配顺序一致）。删除"world 走进程内实现"的日志分支与相关注释。
- `game = WorldMcpTool.build(world_server_url=…)`；返回类型 `tuple[RunHarness, WorldMcpTool]`；模块 docstring 与注释里的 `GameTools` 改为 `WorldMcpTool`。

**D4 world server 命令行加 `--watch` 与 `--speed`。** `mcp_servers/world_server_cli.py`：`--watch`（`store_true`）、`--speed`（`int`，缺省 0）原样传给 `PyBoyWorld(...)`。语义与此前 `build_real` 相同（`watch` 只管开不开窗口，`speed` 只管跑多快，`0` 不限速）。帮助文案写清这两项在 server 所在的机器上生效。

**D5 评测调用点（最小改动，真正的迁移在批 ③）。**
- `evals/agent_short_goal_run/solver/runner/one.py`：`build_real(...)` 调用去掉 `ROM`、`None`（state）、`speed`、`watch`，其余不变。其上游的 `speed` / `watch` 管线（`solver.py`、`worker.py`、`task.py`、`config.json`）本批**不动**，留给批 ③ 清理。
- `evals/agent_short_goal_run/dataset/build/pack.py`：去掉 `ROM`、`str(state)`、`speed=0`；并在 `pack` 的入口处加一个**大声失败的保护**（`raise NotImplementedError`，文案：打包的起点存档尚未经 MCP 载入，待 mcp-only 批 ③；不要在此之前打包），防止从错误的起点静默打出错误存档。若有现成测试会真走到这里，**停下汇报**，不自己绕过。批 ③ 会删这个保护。
- 其余评测脚本（`world_case.py` 等直接 `new PyBoyWorld` 的）本批不动。

**D6 文档与说明。** 同步改掉这些现行说法（历史文档与 CHANGELOG 旧条目不改）：
- `AGENTS.md` / `CLAUDE.md` 目录树里"`GameTools.build(rom, …, world_server_url=?)` 造 world 实现（配了 URL 走 MCP，缺省进程内）"一句（**只改这一处事实性写法，规范性内容不动**）。
- `docs/spec/tools/SPEC.md`、`docs/spec/mcp/SPEC.md`、`docs/spec/build/SPEC.md` 里 `GameTools` 的描述、`world_server_url` 缺省进程内的说法。
- `mcpclient/world_tool.py` 里"原 GameTools 的信封翻译随迁"一类 docstring；并把批 ②a 时被缩短的 `execute` docstring 补回"所有公开脚本走同名 tool；内部 shop_buy/shop_sell 由买卖脚本组合调用"这一句。
- `world/action_space.py` 顶部说明里"tool 层只在进程内模式调用掩码"的过时措辞（executor 在批 ②a 报告）——只改这一处说明文字，不动代码。
- `scripts/check_world_self_contained.py` docstring 中的 `GameTools.build`；`tests/assembly/test_build.py` docstring 中的 `GameTools.build(rom)`。

## 三、测试

**迁移 / 调整**
- `tests/mcpclient/world_tool/test_world_mcp_parity.py`（**v2 新增裁决**）：它拿 `GameTools` 当基准，`GameTools` 删除后改为以共用纯函数和原契约文本为基准，用例意图不变：
  - 动作空间与 prompt 对照：把 `GameTools(world).get_action_space(...)` 换成 `action_space_for(observation, list(ALL_BUTTONS))` 作为"本地基准"，prompt 全文逐字节对比保留；
  - 前置失败用例：不再构造 `GameTools`，改为断言 MCP 路径抛出的 `AssertionError` 文本等于**字面期望文本**——键：`f"execute() got {name!r} outside {space.names}"`（`space` 取 `action_space_for(observation, list(ALL_BUTTONS))`）；多键：`"execute() 只接受单键动作；连按应由 Harness 的循环展开成多步"`；脚本：`f"execute() got script {name!r} outside {script_names}"`（`script_names` 为该空间里 `kind == "script"` 的条目名列表）；`client.calls == []` 保留；
  - 文件改名为 `test_world_mcp_contract.py`（旧文件删除），模块与用例 docstring 里"同进程内路径一致 / 同 GameTools"的措辞改成当前事实。
- `tests/mcpclient/game_tools/test_game_tools_action_space.py`：被测的是 `mcpclient/action_space.py`，按"测试目录镜像源码"移到 `tests/mcpclient/action_space/test_action_space.py`，用例内容不变（旧文件删除，旧目录若变空一并清掉）。
- 所有 `monkeypatch.setattr(assembly.GameTools, "build", …)`（`tests/budget/test_run_config.py`、`tests/evals/agent_short_goal_run/test_budget_wiring.py`、`tests/mcpclient/memory_tool/test_memory_mcp_only.py`）改为对 `assembly.WorldMcpTool` 的 `build`；这些测试里的 `build_real(...)` 调用同步去掉被删参数。
- `test_memory_mcp_only.py::test_build_real_without_memory_url_fails_at_assembly`：现在 world 检查在前，该用例要先让 world 通过（给 `world_server_url` 并替换 `WorldMcpTool.build` 与对 world 的 `assert_mcp_server_ready`），再断言 memory 缺地址报错；不得放松断言。
- `tests/mcpclient/world_tool/test_mcp_world_tool.py` 的模块 docstring 里"与进程内 `GameTools` 的契约逐条对齐"改成当前事实。

**新增**（放 `tests/mcpclient/world_tool/` 与 `tests/mcp_servers/`）
- `test_world_build_requires_a_server_url`：`WorldMcpTool.build(world_server_url="")` 抛 `ValueError`，文案含 `MCP_WORLD_SERVER_URL`。
- `test_build_real_without_world_url_fails_at_assembly`：清掉 env、不传参数，`build_real` 抛 `McpTransportError`，文案含 `MCP_WORLD_SERVER_URL`，且在任何探活或 `MemoryTool.build` 之前；破坏验证见第五节。
- `test_world_server_cli_passes_watch_and_speed_to_the_world`：用假 `PyBoyWorld` 记录构造参数，断言 `--watch --speed 1` 时收到 `watch=True, speed=1`，缺省时 `watch=False, speed=0`；不起端口、不起模拟器、不 `mcp.run`。

## 四、允许改动的文件

生产：`pokemon_agent/build.py`、`pokemon_agent/mcpclient/world_tool.py`、`pokemon_agent/mcpclient/game_tools.py`（删除）、`pokemon_agent/mcpclient/__init__.py`（若有再导出）、`pokemon_agent/mcp_servers/world_server_cli.py`、`pokemon_agent/world/action_space.py`、`pokemon_agent/world/scripts/catalog.py`（二者都只改说明文字；后者仅第 182、216 行提到 `GameTools.execute` 的两处，改为指向 server 的脚本 tool / `WorldConsole.run_script`，不动任何代码）。
评测：`evals/agent_short_goal_run/solver/runner/one.py`、`evals/agent_short_goal_run/dataset/build/pack.py`。
测试：第三节列出的文件及新增用例所在文件。
文档与脚本：D6 列出的各处；`CHANGELOG.md`（四段，+10 行左右，编号 481）。
其他一律不动。

## 五、验证

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 全绿。
- 搜索：`PyBoyWorld(` 在 `pokemon_agent/` 内只出现在 `mcp_servers/world_server_cli.py`（与 `world/` 自身）；`GameTools` 在现行代码与现行文档中零出现（CHANGELOG、`changelog/`、历史 `docs/` 除外）；`build_real(` 的所有调用点都不再传 `rom` / `state_file` / `watch` / `speed`。
- 破坏验证：临时删掉 `build_real` 的缺 world 地址报错，对应用例必须失败；临时去掉 server CLI 里把 `watch` 传给 `PyBoyWorld` 的那一项，CLI 用例必须失败；恢复后转绿。
- 汇报 `state_schema_hash`，应为 `4f1cac6fcc7216d5`。

## 六、停止条件

- 需要改第四节之外的文件；起点不是全绿；`HEAD` 与交接不符。
- 有现成测试会真走到 `pack.py` 的入口（保护会让它失败）。
- 某个 `build_real` 调用点因位置参数顺序变化无法确定正确改法。
- `GameTools` 删除后发现还有生产代码在用它的某个方法（`evolve` 等）。
- 需要改 `world_server.py`、任何 prompt 文件，或 `PyBoyWorld` 的行为。
- 需要改 `CLAUDE.md` / `AGENTS.md` 的规范性内容。

## 七、非目标

评测脚本的迁移与 `speed` / `watch` 管线清理（批 ③）；`evals/common/world_case.py`；world server 的租约逻辑；`memory_local.py` 改名；`evolve`。
