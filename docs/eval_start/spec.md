# 评测轻起点 + 评测自起临时服务 —— spec（v1.0，2026-10-23）

依据：`docs/eval_start/intent.md`。三个检查点，CHANGELOG 编号 606 / 607 / 608。起点：本分支上「删除作废存档」的提交（各数据集版本的 `archives/` 目录已删）。

## 一、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | 评测起点 = 样本自带的原始 `.state`（`sample.start.source_state`，哈希 `source_sha256`）。每条样本现建 `Task(task_id=sample_id, goal, success_criteria, max_steps, initial_state_hint)`，起跑路径与 `pack_one` 一致：`build_real(config)` → `game.use_start_state(state_path)` → `harness.run(run_id, [task])`（即 `new_run`）。不调用 `restore_run` / `open_branch`；不调用记忆还原 | `new_run` 现建的 `RunState` 与 pack 当时落盘的是同一路径，行为等价 |
| D2 | 不校验 `state_schema_hash`；`CheckpointIncompatible` 在评测侧不再处理 | 改状态结构不再使评测失效 |
| D3 | `validate_start`（`party_healed`、`shop_cancelled` 两类）从 pack 挪到 `run_one` 起跑前：`game.use_start_state` 后 `perceive_task()` 校验，不满足 → 写 `invalid`（原因含样本与检查名），不进图 | 起点不合格是数据问题，不是模型错误 |
| D4 | 样本契约不改冻结文件：`SampleStart.kind` 放宽为 `Literal["archive", "state"]`（旧文件的 `"archive"` 继续合法，语义等同 `"state"`）；`archive` 字段改为可选缺省 `""` 且**被忽略**；`source_state`、`source_sha256` 改为必填（缺失 → `ValueError`）。`loader.py` 删除对 `archives/<名>/manifest.json` 与 `memory_archive` 的检查，改为核 `source_state` 文件存在、字节哈希等于 `source_sha256`，不符 → `DatasetError`。`samples.jsonl` / `revision.json` / 冻结哈希均不改 | 不动冻结数据；旧版本里 `.state` 缺失的版本照旧加载失败，不属本项 |
| D5 | 删除：`evals/agent_short_goal_run/dataset/build/pack.py`、`evals/agent_short_goal_run/solver/runner/archive.py`、`tests/evals/agent_short_goal_run/test_pack_mcp.py` 及其他只测存档/打包的用例；`one.py` 删掉 `prepare_archive`、`restore_run`、`CheckpointIncompatible` 相关代码与 import，docstring 同步；`schemas.py` 的 `SampleStart` 说明改写；`revision.json` 里提到 `pack.py` 的 `repack_note` 不改（冻结文本） | 无存档即无打包 |
| D6 | 新增模块 `evals/common/eval_services.py`，复用 `capture_services.py` 的原语（`available_port`、`start_process`、`wait_ready`、`stop_process`；`capture_services.py` 行为不变，必要时只允许做不改行为的小重构以复用 `_memory_config`）。只提供一个公开上下文管理器 `eval_services(*, world: bool, memory: bool, knowledge_source: Path \| None = None, admin: bool = False, export_env: bool = True)`，进入时起服务并 yield 生效的环境字典，**退出（成功、失败、取消）即关闭服务并清理**，不用 `atexit`、不做进程级单例。评测用原生命令启动，不加包装命令；需要服务的 solver / 脚本在**内部**用它把一次 solver 运行包起来 | 服务生命周期与一次 solver 运行严格同长；并发使用互不干扰 |
| D7 | 起服务行为：临时根用 `tempfile.mkdtemp`；world、memory 各用其下子目录与 `available_port()` 的空闲端口；`memory=True` 时数据根 `<根>/memory` 里先建 `knowledge_memory/`，`knowledge_source` 非空则复制其中 `*.md`（仅文件，不带 index / vectors）；`admin=True` 才给 memory 服务加 `--enable-admin`（只有仍用 memory 管理工具的评测才开）；退出时关服务、删临时根，服务日志复制到 `eval_results/eval_runs/<时间戳>/`。起服务阻塞（最多等 60 秒探活），在 async solver 中须放进线程池执行 | 与采集「独立端口、独立目录」同一套写法；admin 面默认不开 |
| D8 | yield 的字典含 `MCP_WORLD_SERVER_URL`、`MCP_MEMORY_SERVER_URL`（形如 `http://127.0.0.1:<端口>`，**不带 `/mcp`、不带结尾斜杠**，只含实际启动的）、`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。`export_env=True`（默认）同时写进本进程 `os.environ`，退出恢复原样；`False` 时不碰 `os.environ`，调用方把字典传给子进程。**需要的那个服务对应的 URL 变量已有值时，不启动该服务，直接复用**（调试逃生口），并打印一行说明 | 从源头杜绝 `/mcp` 后缀写错；保留手动起服务的口子 |
| D9 | 接入三处，都在 solver / 脚本内部 `with eval_services(...)` 包住一次 solver 运行：①`agent_short_goal_run`：`evals/agent_short_goal_run/solver/solver.py` 的 `run_one_solver.solve`（一个样本一个 epoch；`world=True, memory=True, knowledge_source=仓库 memory/knowledge_memory/, export_env=False`，字典传给 worker 子进程，`sample_overlay` 读 URL 的来源随之调整，并发样本互不串用）；②`world_script_execute`：`evals/world_script_execute/solver.py` 里一次评测运行的最窄入口（`world=True, memory=False`；执行方读代码确认入口并汇报）；③`memory_store_recall`：`evals/memory_store_recall/solver.py::run_memory`（`world=False, memory=True, admin=True, knowledge_source=None`，评测口径不变） | 每个样本有自己独立的临时 memory 与 world；memory_store_recall 不引入 knowledge 以免改变其结果口径 |
| D10 | `state_schema_hash`、harness `checkpoint/**`、memory `store.py` 全部不改；各检查点汇报 `state_schema_hash` 现算值（应为 `e3bd23162bfd0e85`） | 生产零变化 |

## 二、检查点

### CP1（606）——轻起点

- 改：D1–D5。
- 允许改动的文件：`evals/agent_short_goal_run/solver/runner/one.py`、`evals/agent_short_goal_run/solver/runner/archive.py`（删）、`evals/agent_short_goal_run/dataset/build/pack.py`（删）、`evals/agent_short_goal_run/dataset/schemas.py`、`evals/agent_short_goal_run/dataset/loader.py`、`evals/agent_short_goal_run/dataset/build/__init__.py`（如有导出）、`tests/evals/agent_short_goal_run/**`、`CHANGELOG.md`。若 `validate_start` 所在模块需要小改，执行方先在汇报中说明路径再改（限 `evals/` 内）。
- 测试（不起真服务、不调真模型、不跑 PyBoy）：
  1. 加载：旧 `"archive"` 样本在 `.state` 存在且哈希相符时加载成功；`.state` 缺失 / 哈希不符 → `DatasetError`；`source_state` 缺省 → `ValueError`。
  2. `run_one`：用假 `build_real`（记录调用）验证：现建的 `Task` 字段取自样本；`use_start_state` 在 `harness.run` 之前以样本 `.state` 路径调用；不出现 `restore_run`、`prepare_archive`。
  3. `validate_start` 不满足 → `run.json` 的 `invalid` 非空、`harness.run` 未被调用；满足 → 正常调用。
  4. 删除后 `grep -rn "restore_run\|prepare_archive\|build.pack" evals tests` 无命中（允许 `harness/checkpoint` 自己的用例）。
- 验证：默认 pytest、`ruff check`、`ruff format --check`、`python scripts/check_prompt_boundary.py`、`python scripts/check_world_self_contained.py` 全绿；至少对生产代码做一次破坏验证（例如把 `validate_start` 调用移除，测试 3 应失败，还原后 diff 为空）。**不得起真实服务、不得真实模型调用。**

### CP2（607）——`eval_services`

- 改：D6–D8。
- 允许改动的文件：`evals/common/eval_services.py`（新）、`evals/common/capture_services.py`（仅不改行为的小重构）、`tests/evals/**`（新增）、`CHANGELOG.md`。
- 测试（不起真服务；启动原语用手写假件替换并记录调用）：
  1. 环境：两个 URL 不带 `/mcp`、不带结尾斜杠；`PYTHONUTF8`、`PYTHONIOENCODING` 已设；`export_env=True` 时 `os.environ` 同步且退出后恢复；`False` 时全程不变。
  2. 复用：对应 URL 变量已有值时不调用启动原语、沿用该值；只有一个已有值时只起另一个。
  3. knowledge：`knowledge_source` 非空时数据根 `knowledge_memory/` 恰为源目录的 `*.md`（无 index / vectors）；为 None 时为空；`world=False` / `memory=False` 时对应服务不起（`memory=False` 也不复制）。
  4. `admin`：`admin=True` 才带 `--enable-admin`。
  5. 关闭与清理：正常退出、块内抛异常、块内被取消三种情况下，启动过的进程都被停止、临时根被删、日志被复制；起服务中途失败时已启动的进程也被停止。
  6. 并发独立：两个同时进行的 `eval_services(export_env=False)` 端口与目录不同，一个退出不影响另一个。
  7. `capture_services` 现有调用与测试保持绿。
- 验证同 CP1。**不得真正起 world / memory 服务，不得真实模型调用。** 另需在汇报里回答一件事：memory 服务启动时是否会从其数据根下的 `knowledge_memory/` 装载 knowledge（读 `memory_server.py` / `store.py` 并给出文件与行号）；若不会，停止并汇报。

### CP3（608）——接入与说明

- 改：D9 三处接入；错误提示与文档改为「脚本会自己起服务；已设置环境变量时复用」；`AGENTS.md`、`CLAUDE.md` 的评测说明同步并保持对应段落逐字一致。
- 允许改动的文件：`evals/agent_short_goal_run/solver/solver.py`、`evals/agent_short_goal_run/solver/runner/one.py`（仅 docstring）、`evals/world_script_execute/solver.py`、`evals/memory_store_recall/solver.py`、`evals/common/world_case.py`（仅错误提示 / docstring）、`evals/dataset/brain_choose/build/collect.py`（仅错误提示 / docstring）、`tests/evals/**`、`AGENTS.md`、`CLAUDE.md`、`CHANGELOG.md`。
- 测试：把各调用点用的 `eval_services` 换成假件，验证三处各以 D9 规定的参数进入并退出一次，块内抛异常时也退出；agent_short_goal_run 的 `knowledge_source` 指向仓库 `memory/knowledge_memory/`；并发两个样本拿到不同环境字典。**不得真正起服务或运行评测。**
- 验证：全绿；`AGENTS.md` 与 `CLAUDE.md` 改动段落逐字一致（给 diff）；旧提示（「先起 … server」「设 MCP_*_SERVER_URL 并先起」）在允许文件中清零，其余命中只列出不改。

## 三、编号台账

| 号 | 内容 | 状态 |
|---|---|---|
| 606 | CP1 轻起点 | 已登记 |
| 607 | CP2 `eval_services` | 已登记 |
| 608 | CP3 接入与说明 | 已登记 |

通宵调优顺延 609–616。

## 四、停止条件

- 改动超出检查点「允许改动的文件」；HEAD 与交接不一致；起点不全绿。
- `state_schema_hash` 与 `e3bd23162bfd0e85` 不同。
- 需要改 harness `checkpoint/**`、memory `store.py`、状态模型，或引入第三方依赖。
- 需要任何真实模型调用，或真正起 world / memory 服务才能验证（测试里不允许）。
- CP2 查到 memory 服务不从数据根装载 knowledge。
- 需要改冻结数据集文件。

## 五、回退

一个检查点一个提交，`git revert <提交>`，不重写历史；CP3 依赖 CP2，回退 CP2 前须先回退 CP3。

## 六、非目标

不改 harness 存档能力；不重打任何存档；不改冻结数据；不做 prompt / knowledge 调优（另案）。
