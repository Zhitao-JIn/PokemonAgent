# plan —— 测评 task 改名 + 数据集重整 + judge 扩容 + choose

> 流程位置：tasks-intent.md → tasks-spec.md → **tasks-plan.md** → PR → production
> 本文件按步追加：**D1**（已随 407 落地）、**S1b**（已随 421 落地，真机验收待用户执行）。

---

## D1 —— 数据生产工具迁入 `evals/dataset/<名>/build/`

### 〇、范围与顺序

- **只搬造数据的工具**（采集 / 构建 / 打包 / 审核），涉及两个数据集包：`frames`、`agent_goal_run`。其余三个数据集包没有生产工具。
- **与 S2 同批落地**：工具里写死了数据位置（`DATASET_DIR` 等），先搬工具、后搬数据会改两遍路径。所以 D1 的每一步都和 S2 中对应数据集包的数据落位放在**同一个 commit** 里；本 plan 只写工具侧的动作，数据侧以"前置"标出。
- **在 S1 之后做**：S1 把 `evals/core/world_case.py` 搬到 `evals/solvers/world_case.py`，工具要 import 它的新位置；数据集包名直接用新名（`agent_goal_run`）。

### 一、搬迁清单

**frames**（来源 `evals/data/frames/`）

| 现文件 | 去向 | 动作 |
|---|---|---|
| `build.py` | **拆**：`load_samples` → `evals/dataset/frames/loader.py`（S2）；其余 → `build/build.py` | 构建部分保留：`build_v2`、`_from_capture`、`_from_probe`、`prelabel`、`_prelabel_probe`、`_overlay_value`、`wram_bytes`、`_name`、`_stuff_bag`、`_png` 与常量 `ROM` / `PROBE_BAG`；`DATASET_DIR` 改指数据集包目录；`STATES`（现指 `experiment/experiment_states/knowledge`）改指 `sources/states/knowledge` |
| `observe.py` | `build/observe.py` | 只被 `build.py` 用（构建时预标），import 改相对 |
| `freeze.py` | `build/freeze.py` | 读用例改为读 `sources/capture_cases.jsonl`；起模拟器改用 `sources/states/` |
| `capture_cases.py` | **转数据**：`sources/capture_cases.jsonl`；`ViewCase` 类型改为 pydantic 放 `build/freeze.py` | 8 条用例逐字段转出（`scene` 存枚举值字符串）；转换后核对条数与字段 |
| `terrain.py` | `build/terrain.py` | 两条地形用例的 `state` 改为相对 `sources/states/` |
| `storage.py` | `build/storage.py` | `DATASET_DIR` 改指数据集包目录；`truth` 的读写路径改用 `loader.py` 导出的常量 |
| `coverage.py` | `build/coverage.py` | 读帧改用 `loader.load()`；入口改 `python -m evals.dataset.frames.build.coverage` |
| `cli.py` | `build/cli.py` | `python -m evals frames build` 由 `evals/cli.py` 转发到这里，命令不变 |
| `dataset/v2/probe_0926.json` | `sources/probe_0926.json` | `build_v2` 的探测帧输入，不是冻结产物；`build.py` 读取路径同步 |

**agent_goal_run**（来源 `evals/data/`）

| 现文件 | 去向 | 动作 |
|---|---|---|
| `pack.py` | `evals/dataset/agent_goal_run/build/pack.py` | 改从本包 `loader` 导入 `DATASET_DIR` / `load_samples` / `sha256_of`；命令 `python -m evals.data.pack` → `python -m evals.dataset.agent_goal_run.build.pack` |

**采集输入存档**（D3 已定：拷贝，`experiment/` 不动）——`evals/dataset/frames/sources/states/` 下保留原相对路径：

- `knowledge/`：`knowledge_battle_action_menu`、`knowledge_battle_item_use`、`knowledge_battle_pokemon_switch`、`knowledge_dialogue_advance`、`knowledge_movement_obstacle`、`knowledge_pc_save`、`knowledge_shop_confirm_purchase`、`knowledge_shop_open_buy_menu`、`knowledge_wild_encounter`（`.state`）
- `macros/`：`battle_faint_switch`、`field_two_mons`、`learn_move`、`player_keyboard`（`.state`）

来源：`probe_0926.json` 的 8 个场景、`capture_cases.py` 的 7 个存档、`terrain.py` 的 2 个存档，去重后 13 个。

### 二、连带改动

1. **`evals/solvers/world_case.py::start_world`**（S1 已从 `evals/core/` 搬来）：现在把 `state` 拼在 `experiment/experiment_states/` 后面（写死的 `STATES`）。改为收**完整路径**（`Path`），由调用方决定存档在哪；`STATES` 常量删除。调用方：`build/freeze.py`、`build/terrain.py`、world_script_execute 的 solver（S2 同批改为传 `v1/states/` 下的路径）。
2. **`evals/cli.py`**：`freeze-frames` 改为 import `evals.dataset.frames.build.{freeze,terrain}`；`frames build` 转发到 `evals.dataset.frames.build.cli`。对外命令不变。
3. **提到旧命令的文字**：`evals/e2e/runner/one.py`（两处 "`python -m evals.data.pack` 重打"）、`evals/data/loader.py`（迁入新 loader 时一并改）、`evals/schema/sample.py`（迁入新 schemas 时一并改）。
4. **出口规则**：`evals/dataset/<名>/__init__.py` **不 import `build`**；`build/__init__.py` 只有模块 docstring。task 运行时 `import evals.dataset.frames` 不应把 pyboy / PIL 拉进 `sys.modules`（`build` 才需要它们）。

### 三、步骤

| # | 动作 | 前置（S2 数据侧） |
|---|---|---|
| 1 | `start_world` 改收完整路径；改 `evals/solvers/world_case.py` 与现有调用方，行为不变 | S1 完成 |
| 2 | 建 `evals/dataset/frames/{build,sources}/`；`git mv` 工具文件（保留历史），拆 `build.py`；拷采集存档；`capture_cases.py` → `sources/capture_cases.jsonl`；改 import 与路径常量 | frames 的 `v2/samples.jsonl` / `truth.jsonl` 与 `loader.py` 同批落位 |
| 3 | 建 `evals/dataset/agent_goal_run/build/`；`git mv pack.py`；改 import 与命令文字 | agent_goal_run 的 `v1/` 与 `loader.py` 同批落位 |
| 4 | 改 `evals/cli.py` 转发 | 2、3 |
| 5 | 文档：`docs/spec/evals/SPEC.md` 的命令与目录；CHANGELOG 一条编号条目 | 2–5 |

### 四、验证

| 验证 | 方法 | 通过标准 |
|---|---|---|
| 工具产物不变 | 迁移后重跑 `python -m evals freeze-frames`（接管 8 帧 + 地形 2 帧，确定性重采） | `v2/samples.jsonl`、`v2/truth.jsonl` 内容与迁移前逐字节相同（迁移前先存一份哈希） |
| 用例转换无损 | `sources/capture_cases.jsonl` 读回的 8 条与原 `capture_cases.py` 的 `CASES` 逐字段相等（迁移脚本里一次性断言） | 8/8 相等 |
| 打包工具可用 | `python -m evals.dataset.agent_goal_run.build.pack --samples <一条>` 打到临时版本目录 | `world.state` 与现有存档逐字节相同；`manifest.json` 除时间类字段外相同 |
| 运行时不拉工具 | 测试：`import evals.dataset.frames` 后 `sys.modules` 里没有 `evals.dataset.frames.build.*`、没有 `pyboy` | 断言通过 |
| 回归 | 全量 pytest（排除已知 `test_screen_text`）、ruff | 不多出失败 |
| 残留引用 | grep `evals.data.frames` / `evals.data.pack` / `experiment_states` 于 `evals/` | 没有命中 |

### 五、风险

| 风险 | 缓解 |
|---|---|
| `freeze-frames` 重跑写回冻结数据，若不确定会污染 v2 | 先在数据集副本上跑并比哈希，相同再在正式目录跑；不同则停下排查，不提交 |
| 工作区另有会话在改 evals（CHANGELOG 记号领先于 git） | 开工前确认无并行改动；一步一 commit，冲突面最小 |
| CRLF / LF 混用导致整文件 diff | 搬迁用 `git mv`，编辑时保留原文件换行风格 |

> `glyphs.py`、`deduplicate.py` 已于 405 删除（无引用的历史工具），不再搬迁。


## 本次落地记录（2026-10-07）

用户限定本次只做移动相关：S1 → S2（含 D1），J1–J3 仍待定，S3、S4 不执行。

- 前置代码与文档先独立提交为 b3af4ef。
- S1 对应 CHANGELOG 406，commit 9ede92f；全量回归与基线均为488 passed、2 skipped。
- S2 对应 CHANGELOG 407：五份数据、样本契约与读取器归 dataset；frames / agent 构建工具归 build；
  106条脚本用例与8条帧采集输入转冻结数据，experiment 原存档保留。
- 106条转换前后完整裁决一致；D1 重采产物与旧工具逐字节一致，但旧工具重跑也不等于现有v2。
  正式冻结文件保持原状；pack 验证使用副本及项目现有的进程内装配模式。

---

## S1b —— agent_goal_run 的过程 trace 进 Inspect transcript

> 规格：`tasks-spec.md` §一b。前置：S1（406）、S2（407）已落地。一个 CHANGELOG 编号条目、一个 commit。
> 参照：`eval_results/trace_view_demo/prototype_trace_view_task.py`（已验证可行的原型；直接读 json 文件、模型名写死，正式实现按 spec 改为 `RunStream` 与真实型号）。

### 步骤

| # | 动作 | 文件 |
|---|---|---|
| 1 | 新增 `AgentRunRecord(StoreModel)`：`run_id`、`branch`、`invalid`、`error`、`work_dir`、`run_result` | `evals/solvers/agent_goal_run/solver.py`（或同包 `record.py`） |
| 2 | 新增回放模块：`replay_into_transcript(stream: RunStream, models: dict[str, str]) -> int`（返回追加的事件数）；按 spec §1b.3 拆成四个小函数：span、model、tool、info；span 栈处理未配对的结束 | `evals/solvers/agent_goal_run/transcript.py` |
| 3 | solver 改造：子进程结束 → 读 `run.json` / `run_result.json` → 写 `AgentRunRecord` → 有效样本 `RunStream.load` 后调 `replay_into_transcript`；无效 / 超时写一条说明性 `InfoEvent`；`state.output.completion` 保持现状 | `evals/solvers/agent_goal_run/solver.py` |
| 4 | task 增加参数 `transcript: bool = True`，透传给 solver；`models` 透传给回放用作型号名 | `evals/tasks/agent_goal_run/task.py` |
| 5 | scorer 改从 store 取记录：删掉自己拼 `work_dir_of(...)`、读 `run.json` 的代码 | `evals/scorers/agent_goal_run/task_scorer.py`、`result_grade.py` |
| 6 | 单元测试（spec §1b.6-1） | `tests/test_evals_agent_transcript.py`（新） |
| 7 | 离线回放核对（spec §1b.6-2）：写一个一次性脚本或测试，对 `eval_results/inspect/runs/knowledge_door_transition/trace` 跑回放，打印各类事件计数与首尾时间 | 不进仓库 |
| 8 | 文档：`docs/spec/evals/SPEC.md` 增加"agent_goal_run 的过程在 Inspect View 的 Transcript 里"一段与事件映射表；删去"过程层只在 Langfuse"的表述；CHANGELOG 一条 | 文档 |

### 验证

| 验证 | 通过标准 |
|---|---|
| 单元测试 | 新测试全过；`tests/test_evals_*` 无新增失败 |
| 离线回放 | 事件计数：ModelEvent = 账本中模型调用账数，ToolEvent = 动作 + 记忆账数，span 成对；首尾时间等于账本最早 / 最晚 `started_at` |
| 回归 | 全量 pytest（排除已知 `test_screen_text` 与已知 trace 分支顺序偶发失败）不多出失败；ruff 通过 |
| 真机（交用户本机） | `python -m evals run agent_goal_run --limit 1` 后 `inspect view` 可见三层嵌套与带图的模型调用 |

### 注意

- 只用 `transcript()._event(...)` 追加；不要用 `transcript().info()` / `async with span()`，它们会把时间戳盖成当前时间。
- 事件 `uuid` 用账的 uuid；同一样本重复回放会因 uuid 重复报错——回放只调用一次。
- 不改项目 trace 的格式与写入方；不改 Langfuse 树形约定。

### S1b 落地记录（2026-10-08）

- 新增 `AgentRunRecord` 与 `RunOneRecord` 文件契约，solver 写 store，两个 scorer 只从
  store 取执行线与路径；task 的 `transcript` 参数缺省 true，false 时不读回放账。
- 回放沿用 `RunStream.load`，覆盖三层 span、全部模型链路、动作和记忆工具及其余信息账。
  原 uuid 归正文事件，派生 span 用后缀 uuid，metadata.trace_uuid 始终指向原账。
  未配对 error 不误关外层，遗留 span 使用最后账 ended_at 收口。
- Inspect 0.3.271 原声明为下限，本次改为精确锁定；回放临时开启全部模型 API 请求保留，
  避免 Inspect 默认只保留前几次完整请求。时间按 datetime 微秒精度保存。
- 新增 8 个无模型、无游戏测试，覆盖原时间与嵌套、图片、完整字段与用量、30 次调用不丢
  请求、重复回放拒绝、历史工具及 enabled / disabled / invalid / timeout 的 store 交接。
- 离线真账经 RunStream 排除 main 的 checkpoint_save：167 条账 → 175 个事件，
  Model 32、Tool 54、Info 81、SpanBegin/SpanEnd 各 4；已生成并读回
  `eval_results/s1b_trace_view/*.eval`，完整请求和原时间通过核对。
- 回归：排除已登记的 `test_screen_text.py` 后全量 pytest 561 通过、2 跳过，无失败；
  `ruff check .`、`ruff format .`、git diff 空白检查通过。沙箱验证使用应用随附 Python 与
  项目 venv 依赖，补齐 Windows DLL 搜索路径，并把 Inspect 验证日志重定向到工作区。
- 真机验收仍由用户本机执行：`python -m evals run agent_goal_run --limit 1`，随后
  `inspect view` 检查三层嵌套、带图模型调用与 Langfuse 同 run 的时间。
