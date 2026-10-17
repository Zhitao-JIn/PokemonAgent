# spec —— 批 ③b：评测脚本改走 MCP

> 流程位置：批 ②b（`8ec5c13`）、批 ③a（`6b2310d`）已提交 → **批 ③b（本文，v1）** → ②b+③a+③b 一起合入主工作区。
> 分支：`refactor/mcp-only`，基线 `6b2310d`，`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 性质：**评测脚本迁移 + 删除已失效的旋钮**。评测真正运行需要用户在本机先起 server；本批验证只做到静态检查与单元测试（含 in-memory 传输），**不起模拟器、不连真实端口、不调模型**。

## 用户决定（2026-10-17）

1. `freeze.py` / `terrain.py` 也走 MCP，读 WRAM 用批 ③a 的 `read_wram`。
2. 评测**全部串行**：只有一个 world server、一个 memory server；`world_script_execute` 的 `--workers` 删除。
3. pack 的起点：`reset` 接受起点（批 ③a 已做），pack 用 `use_start_state`。
4. 删除 `knowledge` 开关：是否带先验由样本存档里的记忆决定（`restore` 以存档为准），不再有拷贝管线。
5. `speed`、`watch` 已是 world server 命令行旋钮（批 ②b），评测侧管线全部删除。

## 一、事实（读码核对，基线 `6b2310d`）

1. `evals/common/world_case.py::start_world` 直接 `PyBoyWorld(ROM, state_path=…)`、`reset`、再 `world.step([(key,1)], settle=True)` 按开跑前的键；`stop_world` 直接 `world._pyboy.stop(save=False)`。调用方：`world_script_execute/solver.py`、`dataset/frames/build/freeze.py`、`terrain.py`。`decode/solver.py`、`dataset/frames/snapshot.py` 只用其中的 `ROM` 路径常量（不起世界），不受影响。
2. `world_script_execute/solver.py::run_case` 用 `run_script_by_name(WorldConsoleAdapter(world), 脚本名, 参数)` 在进程内跑脚本，得到 `ScriptResult(ok, code, data, events)`。world server 对每个脚本有**同名 tool**，返回信封：`{"ok": code=="ok", "code": …, "data": {"ok": 脚本语义成败, "code": …, **脚本 data, "calls": […]}, "events": […]}`；脚本失败码**不**抛异常（信封照回），只有 server 侧异常才成 `McpToolError`。
3. `WorldMcpTool.execute` 带掩码前置断言（动作须在本帧动作空间内且脚本条目 enabled）。评测的「开跑前按键」「直接调脚本（含故意在不合适场合调用）」不应受这条约束——它们没有 `observation`，也不是 harness 的决策。
4. 租约：变更类 tool 的 `client_id` 默认 `harness-<pid>`；`world_script_execute` 每例一个子进程（300 秒墙钟杀进程），`agent_short_goal_run` 每样本一个子进程（超时杀进程）。子进程被杀不会归还租约 → 下一个子进程（不同 pid）被 `rejected`。
5. `run_one`（`agent_short_goal_run/solver/runner/one.py`）：起点存档由 `restore_run` 恢复——它依次 `memory.restore_memory(存档)`、`game.reset(…)`、`game.load_state(存档里的 world.state)`，**不依赖 server 启动时的 `--state-file`**，也不依赖 memory server 的既有内容（`restore` 以 zip 为准，zip 里没有的记录会从库里删掉）。所以 `run_one` 自身无需新增起点逻辑。
6. `pack.py` 现在两个入口首行 `raise NotImplementedError`（批 ②b 加的保护）。`pack_one` 用 `build_real(...)` 拿到 `(harness, game)`，`harness.run(run_id, [task], checkpoint_only=True)`；harness 每个 run 开头 `game.reset`（批 ③a 起可带起点）。pack 的记忆来自 memory server：若 server 里有之前样本的记忆，打出的快照就会混进去。
7. `memory_store_recall/solver.py::run_memory` 用 `MemoryTool.build(memory_root=<临时目录>)`；现在 `MemoryTool.build` 已要求 `memory_server_url`，该文件在基线上**已经不可运行**。它的「每次一个隔离库」要改成：server 是共享的，开跑前把 server 清空。
8. 清空 memory server 的办法：`restore_memory` 用**空 zip**（以 zip 为准 ⇒ 全删）。需要 server 带 `--enable-admin`；`/health` 里有 `admin` 字段。
9. 旋钮管线：`knowledge` / `speed` / `watch` 出现在 `evals/config.json`、`evals/runconfig.py::REQUIRED_KEYS`、`agent_short_goal_run/{task.py,solver/solver.py,solver/worker.py,solver/record.py,solver/runner/one.py}` 以及相关测试；`one.py` 里 `ROM`、`KNOWLEDGE_DIR` 两个常量随之失效。

## 二、决定表

**D1 `WorldMcpTool` 三处小增补**（唯一允许改的生产文件）：
- `press(segments: list[tuple[str, int]], *, settle: bool = True) -> None`：直接调 server 的 `step`，带 `client_id`；**不做掩码断言**；供评测的开跑前按键用。
- `call_script(name: str, args: dict[str, str | int | float | None]) -> dict[str, Any]`：直接调同名脚本 tool，带 `client_id`；**不做掩码断言**；返回 server 的**完整信封**（`ok`/`code`/`data`/`events`）；脚本失败码不抛异常，server 侧异常（`McpToolError`）向上传递。
- 默认 `client_id`：构造时 `client_id` 参数 > 环境变量 `MCP_WORLD_CLIENT_ID`（非空）> `harness-<pid>`。理由见事实 4。`harness` 路径不设此变量，行为不变。

**D2 `evals/common/world_case.py` 改为 MCP**（保留 `ROM` 常量与三个函数名）：
- `world_url()`：`load_env_file()` 后取 `env_str("MCP_WORLD_SERVER_URL")`；空 → 抛 `McpTransportError`，文案同 `build_real` 的 world 缺地址（含 `MCP_WORLD_SERVER_URL`）；非空则 `assert_mcp_server_ready(url, "world")`。
- 模块加载时不设环境变量；函数 `start_world` 内 `os.environ.setdefault("MCP_WORLD_CLIENT_ID", "eval")`（评测进程统一用同一个租约身份）。
- `start_world(state, pre, *, case_id) -> WorldMcpTool`：`WorldMcpTool.build(world_server_url=url)` → `use_start_state(state)` → `reset(Req(task=Task(task_id=case_id, goal="world 用例测评", success_criteria="-", max_steps=1)))` → 对 `pre` 里的每个键 `press([(key, 1)], settle=True)`。存档缺失在 `use_start_state` 读文件时当场报错（基础设施故障，同原语义）。
- `read_frame(world) -> (TaskObservation, RamReadout)`：`world.perceive_task()` 取 `observation` / `ram`，`ram` 非空断言保留。
- `stop_world(world) -> None`：`world.release_lease()`（尽力而为：传输错误不吞，由调用方的 `finally` 语义决定——见 D3）。不再碰任何模拟器私有属性。

**D3 `world_script_execute/solver.py::run_case`**：
- 步骤 1 起世界（D2）；步骤 2 `report = world.call_script(case.script, dict(case.args))`，由信封映射成 `ScriptReport(ok=body["data"]["ok"], code=body["data"]["code"], data={除 ok/code/calls 外的 data 键}, events=body["events"])`；`McpToolError`（server 侧异常）及脚本调用中的其它异常 → `crash=f"{type}: {exc}"`，与原语义一致（「脚本的任何异常都是被测结论」）。
- 步骤 3 读收尾帧；`finally` 里 `stop_world`。`stop_world` 自己抛错时**不得掩盖**步骤 2/3 已有的结论：用 `try/except Exception` 记 `logger.warning` 后继续（租约遗留由 D1 的固定身份兜底）。
- 删除对 `run_script_by_name`、`WorldConsoleAdapter` 的 import。

**D4 `--workers` 删除**：`world_script_execute/__main__.py` 去掉 `--workers` 参数与校验；`dataset/cases.py::build_cases(cases, version)` 去掉 `workers` 形参与线程池，改为顺序 `for`；`hyperparameters` 去掉 `workers`。相关测试同步。

**D5 `freeze.py` / `terrain.py` 改走 MCP**：
- `perceived = world.perceive_task()` 照旧；WRAM 取 `wram = world.read_wram()`（8192 字节，对应地址 `0xC000–0xDFFF`）。
- 新增纯函数 `tiles_from_wram(wram: bytes) -> list[list[int]]`（放 `evals/dataset/frames/build/` 内一个小模块，两处共用）：18 行 × 20 列，`wram[(W_TILEMAP - 0xC000) + row * 20 + col]`；断言 `len(wram) == 8192`。原先 `bytes(memory[0xC000:0xE000])` 压缩进 `wram` 字段的地方用同一份 `wram` 字节。
- 其余逻辑（标签、`ScreenSample` 的字段、`save_frames`）不改；`terrain.py` 里读 `world._pyboy.memory` 的其它用法若有，同样改为从 `wram` 派生；**若有无法由这 8192 字节派生的读取，停下汇报**。
- `finally: stop_world(world)`。

**D6 `pack.py`**：
- 删除两个入口首行的 `NotImplementedError`。
- `pack_one` 步骤：①校验 `.state` 哈希（照旧）；②**清空 memory server**：构造 `MemoryTool.build(memory_server_url=<env 或明确失败>)` 并调用新函数 `clear_memory`（D8）；③`build_real(...)` 取 `(harness, game)`；④`game.use_start_state(state)`；⑤`harness.run(..., checkpoint_only=True)`（其后不变）。
- 打包前置：命令行 `main()` 文档串写明「先起 world server（任意 `--state-file` 或无）与 `--enable-admin` 的 memory server；本命令会清空该 memory server」。
- memory server 地址取自 `MCP_MEMORY_SERVER_URL`，缺则大声失败；不新增命令行参数。

**D7 `memory_store_recall`**：
- `run_memory(dataset, k)`：从 `MCP_MEMORY_SERVER_URL` 取地址（缺则 `McpTransportError`，文案含变量名）；`assert_mcp_server_ready(url, "memory")` 后断言返回的 `health["admin"] is True`，否则抛 `McpTransportError`（文案：评测需要带 `--enable-admin` 的专用 memory server）；`MemoryTool.build(memory_server_url=url, memory_root=<eval_results 下临时目录>)`；`clear_memory(tool)`；然后走原有 `evaluate_memory`。`evaluate_memory` 本体不动。
- 去掉不再需要的 `tempfile` 隔离库（保留 `memory_root` 临时目录给快照用即可）。

**D8 `clear_memory(tool)`**（放 `evals/common/memory_server.py`，`pack.py` 与 `memory_store_recall` 共用）：在临时目录写一个**空 zip**（合法 zip、零条目），调用 `tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=<路径>))`；清理临时目录。前置条件：server 带 `--enable-admin`（否则 restore 被拒，错误向上传递）。后置条件：之后任一 `recall` 无记录。

**D9 `agent_short_goal_run` 删旋钮**：
- 删 `knowledge`：`config.json`、`runconfig.REQUIRED_KEYS`、`task.py` 形参与 `baseline_context.json` 与 metadata、`solver.py` 形参、`worker.py` 透传、`record.py::RunOneRequest.knowledge`、`one.py::run_one` 形参、`knowledge` 拷贝块、`KNOWLEDGE_DIR` 常量及不再使用的 `shutil` import。
- 删 `speed`：同上全链路；`one.py` 中 `ROM` 常量若无他处引用一并删除（先全仓搜索）。
- 删 `watch`：`config.json`、`REQUIRED_KEYS`、`worker.py` 的 `load_config().get("watch")` 与 `one.py::run_one` 形参及注释。
- 保留 `config.json` 其余全部键与取值；`REQUIRED_KEYS` 删这三键后，缺键报错行为不变。
- `one.py` 里 `os`/`json` 等 import 若变为未使用，ruff 会报，清理之。

**D10 `run_one` 的前置提示**：`run_one` 的模块文档与 `evals/` 下的 README / `docs/spec/evals/SPEC.md` 写清评测前置：①world server 已起（带或不带 `--state-file` 均可；`--watch`/`--speed` 在此设置）；②memory server 已起并带 `--enable-admin`，且是**评测专用实例**（pack 与 memory_store_recall 会清空它，`restore` 会覆盖它）；③两个环境变量 `MCP_WORLD_SERVER_URL`、`MCP_MEMORY_SERVER_URL`；④评测串行。

**D11 不动的东西**：`pokemon_agent/` 除 `mcpclient/world_tool.py` 外一律不改；`build.py`、server、`world/`、`memory/`、harness、prompt、`evals/**/dataset` 里的冻结数据、`decode/`、`snapshot.py`、`observe.py`、scorer 的计分逻辑。

## 三、测试

测试全部不起端口、不起模拟器、不调模型；用现有的 in-memory 传输夹具（world：`tests/mcpclient/world_tool/conftest.py` 的假 world；memory：`tests/_doubles/memory_server.py`）。

1. **D1**：`press` 发出 `step`（参数含 `client_id`、`settle`）且对不在掩码里的键**不**断言；`call_script` 对非 ok 码的脚本返回信封而不抛，对 server 侧异常抛 `McpToolError`；`client_id` 三级优先级（参数 > env > `harness-<pid>`，用 `monkeypatch.setenv/delenv`）。
2. **D2**：缺 `MCP_WORLD_SERVER_URL` → `McpTransportError`（含变量名）；`start_world` 的假 world 记录：`reset` 收到 `start_state == 存档字节`，且 `pre` 的键按序各一次 `step`；`stop_world` 之后租约已归还（再用另一个 `client_id` 能推进）。
3. **D3**：`run_case` 在假世界上：脚本信封映射成 `ScriptReport`（`ok/code/data/events` 四项逐项，且 `data` 不含 `ok`/`code`/`calls`）；server 侧异常 → `crash` 非空而 `report` 为 `None`；`stop_world` 抛错不掩盖脚本结论。
4. **D4**：`build_cases` 顺序执行、结果顺序与输入一致；`__main__` 不再接受 `--workers`（传入时参数错误）。
5. **D5**：`tiles_from_wram` 用合成字节核对 18×20 映射的四角与一个中间点；长度不是 8192 → 断言失败。
6. **D6**：`pack_one` 的顺序用假的 `build_real` / `MemoryTool` / `clear_memory` 记录：`clear_memory` 先于 `build_real`；`use_start_state(<state 路径>)` 先于 `harness.run`；哈希对不上仍抛 `ValueError` 且上述都没发生。两个入口不再抛 `NotImplementedError`。
7. **D7**：缺 memory 地址 → `McpTransportError`；`health["admin"]` 为 `False` → `McpTransportError`。
8. **D8**：in-memory memory server 带 admin：先 `memorize` 若干条，`clear_memory` 后按同条件 `recall` 为空；不带 admin 的 server → 错误向上传递。
9. **D9**：`REQUIRED_KEYS` 与 `config.json` 都不再含 `knowledge` / `speed` / `watch`，且两者键集合一致；`RunOneRequest` 无 `knowledge`/`speed`；`agent_short_goal_run` / `run_one_solver` / `run_one` 的签名里无这三项（用 `inspect.signature`）。现有测试里引用这三项的（`tests/evals/agent_short_goal_run/*`）同步改，改法记入汇报。
10. **破坏验证**（执行方做，汇报，每次恢复）：①去掉 `pack_one` 里 `use_start_state` 调用 → 测试 6 须失败；②去掉 `pack_one` 里 `clear_memory` → 测试 6 须失败；③去掉 `stop_world` 里 `release_lease` → 测试 2 须失败；④把 `call_script` 的 `client_id` 去掉 → 测试 1 须失败。

## 四、允许改动的文件

`pokemon_agent/mcpclient/world_tool.py`（仅 D1）；`evals/**`（含 `config.json`、`runconfig.py`、上述各模块、`evals/common/memory_server.py` 新增、`evals/dataset/frames/build/` 内新增小模块）；`tests/**` 中与上列对应的文件及新增文件；`docs/spec/evals/SPEC.md`、`docs/spec/tools/SPEC.md`（若列了 `WorldMcpTool` 方法则补三处）；`CHANGELOG.md`（编号 483，四段式）。
**不得改**：`pokemon_agent/` 其它文件、冻结数据文件、`docs/mcp/*`。

## 五、验收

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 三项通过；`state_schema_hash` 仍为 `4f1cac6fcc7216d5`（实测报出）。
- 全仓搜索（代码与测试，文档按 D10 同步）：`PyBoyWorld`、`_pyboy`、`WorldConsoleAdapter`、`run_script_by_name` 在 `evals/` 与 `tests/evals*` 零出现；`knowledge=`/`speed=`/`watch=` 作为评测旋钮零出现（`tests/` 里与 `PyBoyWorld` 构造、world server CLI 相关的 `speed`/`watch` 除外，列清单汇报）；`NotImplementedError("打包的起点存档…` 零出现。
- 四项破坏验证按 D 汇报。

## 六、停止条件

需要改「不得改」里的文件；`terrain.py`/`freeze.py` 有无法由 8192 字节 WRAM 派生的读取；`call_script` 的信封与 `ScriptReport` 无法一一映射（给出缺口）；全量不绿且不是本批改动引起（已有的定向顺序失败 `test_brain_factory_uses_the_injected_plan_timeout` 只在特定子集下出现，全量通过不算）；需要执行任何 git 写操作；任何一步需要真实 server、模拟器或模型。

## 七、非目标

`evals/dataset/frames/build/build.py`（直接用裸 PyBoy 采帧的离线数据集工具，不经 `PyBoyWorld`，本批不动，留作遗留项汇报）；多 server 并发；world 或 memory server 的协议变化；评测数据集内容变化；scorer 计分逻辑；`speed`/`watch` 在 world server 命令行之外的任何新入口；真实评测运行（由用户在本机起 server 后确认，且需对照改前结果核对 `world_script_execute` 的 `ScriptReport` 是否逐项一致）。
