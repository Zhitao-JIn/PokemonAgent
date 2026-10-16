# spec —— 第二阶段：其余任务按类迁入 `evals/<任务名>/`
> 视觉感知档已于 2026-10-16 删除，见 docs/perceive/remove-vision-spec.md；本文为历史记录，正文未改。

> 流程位置：intent.md（`docs/eval/eval-split-intent.md` 第十节）→ **spec.md（本文）** → plan.md → PR → production
> 状态：**v7 已按用户授权实施**；验收 6 的两个新入口已执行，agent 的有效目标运行受既有冻结存档结构不兼容限制。第一阶段（decode）已完成，见 `docs/eval/eval-split-spec.md`（提交 430–434）。
> 起草：2026-10-13
> 范围：把 `evals/` 下其余五个 task 迁完。三个 B 类（memory_store_recall、world_script_execute、episode_vision_read）改为 DeepEval 入口；两个 C 类（brain_goal_judge、agent_short_goal_run）只换目录，仍是 Inspect task。
> 约束：被测系统（`pokemon_agent/`）、冻结数据、真值、判定语义一律不改；只动 `evals/`、`tests/`、`scripts/` 与文档。

---

## 〇、暂定项（按推荐写入，可推翻）

| 编号 | 暂定方案 | 影响小节 |
|---|---|---|
| D1 | 迁完后 `evals/solvers/`、`evals/scorers/`、`evals/tasks/` 三个目录消失；每个任务一个目录 `evals/<任务名>/`。`evals/dataset/` 保留，只放多任务共用的数据集与数据工具 | §三 |
| D2 | 共用数据集留在原处：`evals/dataset/frames/`（含 `build/`）、`evals/dataset/io.py`、`evals/dataset/errors.py` 都不动；多任务共用的代码放 `evals/common/`（`world_case.py`、`run.py`）；`config.json`、`runconfig.py`、`paths.py` 留在 `evals/` 根 | §一、§三 |
| D3 | 公共 DeepEval 运行器 `evals/common/run.py`：从 decode 的 `__main__.py` 抽出，三个新 B 类与 decode 共用；decode 随之改用它，行为不变 | §一 |
| D4 | 每个任务目录内：文件少用单文件（`solver.py`、`scorer.py`、`compare.py`），文件多用同名子包；数据版本目录（`v1/` 等）挨着加载代码放，不单独成顶层 | §三 |
| D5 | 公开任务目录改为 `evals/registry.py`：每项标明 `deepeval`（入口 `python -m evals.<名>`）或 `inspect`（入口 `evals/<名>/task.py`）。公开任务共六个：四个 B（decode、world_script_execute、memory_store_recall、episode_vision_read）、两个 C | §一、§六 |
| D6 | 三个新 B 类沿用 decode 的口径：一个状态一个 `LLMTestCase`、确定性自写指标、缺标/无从判记 N 并跳过、DeepEval 原生输出汇总、有失败时退出码 1 | §二 |
| D7 | world_script_execute 的分组统计改为"每个脚本一个指标 `pass.<脚本名>`"（只挂在该脚本的用例上），取代 `grouped(accuracy(), "script")`；原 `kind_accuracy` 不再单列 | §二、§五 |
| D8 | episode_vision_read 正常调模型，不做运行清单和回放；视觉调用本身不通（网络、密钥、网关）的帧不造用例、不进分母，运行时打印一行列出这些帧，不设专用退出码 | §二 |
| D9 | 每个任务单独一个提交，顺序：memory_store_recall → world_script_execute → episode_vision_read → C 类目录迁移 → 收尾；每个任务先导出迁移前基线再改 | §九 |

---

## 一、前置与共享件

**执行记录**：用户授权代为提交积压改动，P0 已完成。S4 验收按用户明确授权改为每个已核对场景一帧（9 帧），旧基线与新入口各一次；默认 45 帧行为保留，全量视觉验收未执行。world 的纯比较包入口因重写显示删除与新增，用户确认允许；其余实际代码与数据保持重命名。串行 20.8→83.78 秒的隔离代价已获接受。

**1.0 前置（P0）。** 当前工作区有 125 项未提交改动，主要是 `agent_goal_run` → `agent_short_goal_run` 改名（旧路径显示为已删除、新路径为未跟踪）以及 `evals/cli.py`、`evals/__main__.py` 的删除。这批改动必须先由用户提交（或明确保留方式），再开始本阶段。**未提交就不要动手**：本阶段会 `git mv` 整个 `agent_short_goal_run`，与未跟踪文件混在一起会丢历史。

**1.1 `evals/common/run.py`**（从 `evals/decode/__main__.py` 抽出，逻辑不变）

`run_evaluation(*, test_cases, metrics, results_folder: str, hyperparameters: dict) -> int`

- 模块最开头、`import deepeval` 之前设置 `DEEPEVAL_TELEMETRY_OPT_OUT=YES`；stdout 为 `TextIOWrapper` 时改 UTF-8。
- 调 `evaluate(...)`，参数与现 decode 一致：`AsyncConfig(run_async=False)`、`CacheConfig(write_cache=False)`、`ErrorConfig(skip_on_missing_params=True, ignore_errors=False)`、`DisplayConfig(print_results=True, display_option=FAILING, results_folder=results_folder, show_indicator=False, inspect_after_run=False)`。
- 返回 1 当且仅当存在 `success is False` 的用例，否则 0。
- decode 的 `__main__.py` 改为调它；decode 的命令行和输出不变。

**1.2 `evals/common/world_case.py`**：由 `evals/solvers/world_case.py` 原样移入（`git mv`），只改 import。`evals/dataset/io.py`、`errors.py` 不动。

**1.3 `evals/dataset/frames/`**：不动。各任务从它加载，只有任务自己的 dataset 代码搬走（见 §三）。

**1.4 `evals/registry.py`**：

```python
TASKS: dict[str, TaskEntry]   # TaskEntry(kind: Literal["deepeval", "inspect"], entry: str)
```

`deepeval` 的 `entry` 是模块名（如 `evals.decode`），`inspect` 的 `entry` 是 task 文件路径。取代 `evals/tasks/registry.py`。

---

## 二、三个 B 类任务的契约

三者都遵循第一阶段的结构：`dataset.py`（造用例）、`solver.py`（跑被测对象）、`compare.py`（纯判定，不依赖 deepeval）、`scorer.py`（指标）、`__main__.py`（入口，调 `run_evaluation`）。判定语义逐字不变，只换承载方式。

### 2.1 memory_store_recall

**被测对象**：真实 `MemoryTool` 的写入、读回、检索；本地 embedding 与 reranker，不调 LLM。数据：一份冻结库（现 3 条记录、3 条查询），`k` 默认 5。

**用例**
- 每条记录一个用例：`name="store:<record_id>"`，`input` 为该记录的检索语句，`actual_output` 为 JSON `{"problems": [...]}`（取自该记录的存储问题），`additional_metadata={"kind": "store"}`。
- 每条查询一个用例：`name="query:<query_id>"`，`input` 为查询文本，`actual_output` 为检索到的 `record_id` 列表（JSON），`expected_output` 为 `relevant` 列表（JSON），`retrieval_context` 同 `actual_output`，`additional_metadata={"kind": "query"}`。

**指标**（均不调 LLM，`threshold=1.0`，构造参数以同名属性保存）
- `StorageMatch`，名 `storage`：`problems` 为空 → 1.0，否则 0.0，`reason` 为问题文字。只挂 `store` 用例。
- `RecallAtK(k)`，名 `recall_at_k`：分值取 `retrieval_metrics` 的 recall。只挂 `query` 用例。
- `ReciprocalRank(k)`，名 `mrr`：分值取 `retrieval_metrics` 的倒数排名。只挂 `query` 用例。
- 用例种类不符时抛 `MissingTestCaseParamsError`，被跳过。

**solver**：`MemoryRun` 改为普通 `BaseModel`（不再是 inspect `StoreModel`）；`evaluate_memory`、临时库、`MemoryTool.build(...)` 的逻辑不变。`retrieval_metrics` 搬入 `compare.py`。

**输出读法**：`storage` 看 Pass Rate；`recall_at_k`、`mrr` 看 Average Score（Pass Rate 只表示"满分比例"）。

### 2.2 world_script_execute

**被测对象**：真模拟器上执行一次脚本，前后两帧；不调 LLM。数据：`v1/cases.jsonl`，现 106 条用例、38 个脚本。

**用例**：每个 `ScriptCase` 一个。`input` 为调用式（如 `shop_buy(item='...')`），`name` 为 `case_id`，`expected_output` 为 `ScriptCase` 的 JSON，`actual_output` 为 `ScriptRun` 的 JSON（含自报、前后观测与 RAM 读数、崩溃信息、耗时）。

**指标**（不调 LLM）
- `ScriptSide("code")`，名 `code`：自报面，`judge_case(...).code_problems` 为空 → 1.0。
- `ScriptSide("truth")`，名 `truth`：真值面，`truth_problems` 为空 → 1.0。
- `ScriptPass(script)`，名 `pass.<脚本名>`（现 38 个）：该用例脚本名相符才挂（否则 `MissingTestCaseParamsError` 跳过），两面都过 → 1.0。
- 指标内部：`ScriptCase.model_validate_json(expected_output)` 与 `ScriptRun.model_validate_json(actual_output)` 后调搬入 `compare.py` 的 `judge_case`；`reason` 为问题清单（与现 `explanation` 同文）。
- 整体 Pass Rate = 一条用例的所有指标都过 = 原 `pass`（两面都过）。

**solver**
- `script_solver` 的核心（起模拟器、加载状态、执行脚本、取前后帧）改为普通函数 `run_case(case) -> ScriptRun`，逻辑不变；崩溃进 `ScriptRun.crash`，仍保持"`report` 与 `crash` 恰好一个有值"。
- 单条用例墙钟上限 300 秒（现由 Inspect 的 `time_limit` 保证）必须保留等价保护：首选每例子进程隔离，超时即杀，记 `crash="超时"`；若代价过大，停下来报告，**不要静默去掉超时**。
- 用例间默认串行；可选 `--workers N`（默认 1）。

**序列化前提**：`ScriptRun` 含 `TaskObservation`、`RamReadout`，必须能 JSON 往返且 `judge_case` 的结果不变（S0 的测试要验证）。若不能，退路是在 solver 阶段先算出 `ScriptVerdict`，`actual_output` 放判定结论，指标只读结论；走退路前先报告。

**compare.py**：搬入 `judge_case`、`probe`、`_judge_report`、`_judge_truth`、`judge_declared_checks`（原 `checks.py`）与 `ScriptVerdict`。

### 2.3 episode_vision_read

**被测对象**：视觉模型读单帧截图（生产感知节点 `perceive_visual`）。调 LLM，但被测的是视觉模型，指标是确定性的，对照人工标注。数据：`frames/v2`，排除 `takeover_snapshot` 与 `terrain_snapshot` 来源；默认只用 `label_checked` 的帧。

**用例**：每帧一个。`name`/`input` 为 `sample_id`；`actual_output` 为 JSON `{"parsed": bool, "failure": str, "scene", "overlay", "dialog_text", "options", "cursor"}`（解析失败时只有前两项）；`expected_output` 为 JSON，**只含这一帧可判的项**——键缺失即"无从判"：
- `scene`：`_scene_truth(label, memory)` 不为 None 才有；
- `overlay`、`parsed`：总是有（`parsed` 的期望为 `true`）；
- `dialog_text`：标注 `overlay == "dialog"` 才有；
- `options`：`overlay == "choice"` 且标了选项才有；
- `cursor`：`overlay == "choice"` 且标了光标才有。
真值在造用例时一次算好（包括依赖 WRAM 快照的 `scene`），指标不再回头读样本。

**指标**（6 个，名 `scene`、`overlay`、`dialog_text`、`options`、`cursor`、`parsed`，不调 LLM）
- 期望里没有该键 → `MissingTestCaseParamsError` 跳过（等价于原 N）。
- 解析失败（`parsed` 为假）：可判的视觉项一律 0.0、`parsed` 为 0.0，`reason` 为失败原因（等价于原"尝试失败的判定"）。
- 否则逐项比较，比较规则逐字沿用：`scene`、`overlay` 直接相等；`dialog_text`、`options`、`cursor` 先规整空白（`_flat`）再比；`parsed` 恒为 1.0。

**solver**
- `perceive_sample`、`PerceiveRun`、`ProviderUnreachable` 搬入 `solver.py`，逻辑不变；`PerceiveRun` 不再用 `StoreModel`。
- 视觉模型缺省取 `evals/config.json` 的 `models.vision_model`，`--vision-model` 覆盖；`load_env_file()` 照旧。
- 并发 `--workers N`（默认 4），线程内调模型。
- 视觉调用不通（`ProviderUnreachable`）的帧不造用例、不进分母；运行结束前打印一行，列出这些帧的 id 与原因。其余失败照常按退出码 1 处理。

**compare.py**：搬入 `SCENE_TRUTH`、`_scene_truth`、`_flat` 与新的 `truth_fields(sample) -> dict`、`field_verdict(got, want, key)`；`judge_facts` 的语义由它们复现。

---

## 三、目录与改动清单

### 3.1 目标布局

```
evals/
├── config.json  runconfig.py  paths.py  registry.py
├── common/        # world_case.py run.py
├── dataset/       # 只留共用数据：frames/（含 build/、v1、v2、snapshot.py）、io.py、errors.py
├── decode/        # 第一阶段已完成；__main__ 改用 common.run
├── memory_store_recall/
│   ├── __main__.py  dataset.py  solver.py  compare.py  scorer.py
│   └── v1/dataset.json   # 数据版本目录与加载代码同放；加载与 schema 并入 dataset.py（现 loader 25 行 + schemas 31 行）
├── world_script_execute/
│   ├── __main__.py  solver.py  compare.py  scorer.py
│   └── dataset/       # loader.py schemas.py build/ v1/（cases.jsonl + states/，体量大，保持子包）
├── episode_vision_read/
│   └── __main__.py  dataset.py  solver.py  compare.py  scorer.py
├── brain_goal_judge/     # Inspect
│   └── task.py  dataset.py  solver.py  scorer.py  metrics.py  v1/dataset.jsonl
└── agent_short_goal_run/ # Inspect
    ├── task.py  bridge.py
    ├── dataset/    # loader.py schemas.py build/ v1/
    ├── solver/     # 原 solvers/agent_short_goal_run/（含 runner/）
    └── scorer/     # 原 scorers/agent_short_goal_run/ + judged.py verdict.py utils.py redlines.py stream.py registry.py rules/
```

C 类的搬迁理由（依赖已查）：`judged`、`verdict`、`utils`、`redlines`、`stream`、`registry`、`rules/` 仅被 `agent_short_goal_run` 使用，`judge_metrics.py` 仅被 `brain_goal_judge` 使用，`bridge.py` 仅被 `agent_short_goal_run` 使用；`episode_vision_read` 迁成 B 类后不再用 `judged`。

### 3.2 移动与删除

全部用 `git mv` 保留历史，移完删空目录：
- 删除：`evals/tasks/`（含 `registry.py`）、`evals/solvers/`、`evals/scorers/`；`evals/dataset/` 里各任务自己的子目录移走后，只剩 `frames/`、`io.py`、`errors.py`。
- B 类的 inspect 版 `task.py`、`solver`、`scorer` 在各自提交里删除，不留兼容层。

### 3.3 修改

- 全仓 import 与模块路径：`evals.solvers.world_case` → `evals.common.world_case`，各任务的 `evals.{dataset,solvers,scorers,tasks}.<名>` → `evals.<名>`。`evals.dataset.frames`、`io`、`errors` 的路径不变。
- `tests/`：`test_evals_tasks.py`、`test_evals_datasets.py`、`test_evals_perceive.py` 等凡 import 旧路径的；`test_only_the_five_…` 改为断言 `evals.registry.TASKS` 恰好六项，并检查每项入口存在（`deepeval` 项有 `__main__.py`，`inspect` 项有 `task.py` 且含同名 `@task`）。
- `AGENTS.md`、`CLAUDE.md`（保持同步）、`docs/spec/evals/SPEC.md`、`docs/eval/tasks-spec.md` §1.4、`docs/eval/eval-split-spec.md` 里的路径与命令；历史文档只加说明性标注。
- `CHANGELOG.md`：每个提交一条新条目，不改旧条目。
- `.gitignore`：`eval_results/` 已覆盖运行产物，无需新增。

---

## 四、运行方式

```powershell
# B 类（DeepEval）：整体 Pass Rate + 逐指标 Aggregate Metrics，只列失败用例
python -m evals.memory_store_recall [--k 5] [--version v1]
python -m evals.world_script_execute [--case ID]... [--script NAME]... [--version v1] [--workers 1]
python -m evals.episode_vision_read [--vision-model M] [--per-scene N] [--all] [--workers 4]

# C 类（Inspect）：路径改为任务目录
inspect eval evals/brain_goal_judge/task.py
inspect eval evals/agent_short_goal_run/task.py
```

`--case`、`--script` 给了不存在的 id 或脚本名，当场报错（保持原"拼错不静默跑空集"）。`--all` 表示连未人工核对标注的帧也跑（原 `checked_only=False`）。

---

## 五、口径变化

**有意调整：**
- memory_store_recall：原来一个样本带 `storage` 与 `retrieval` 两个 scorer，现在改为逐记录的存储判定与逐查询的 recall@k、MRR；均值由 DeepEval 的 Average Score 给出，与原均值数值一致。
- world_script_execute：按脚本的准确率由 `pass.<脚本名>` 指标给出；原按 `kind` 的分组准确率不再单列（需要时从逐脚本结果推）。
- episode_vision_read：每列的 `judged_accuracy` / `judged_count` 变为每个指标的 Pass Rate / Total；N 仍不进分母。

**不变：** 所有判定语义、数据集、真值、模型配置、`config.json` 取值方式。

---

## 六、验收

1. **逐项等价（每个 B 类任务先导出迁移前基线，S0）**：
   - memory_store_recall：每个 `record_id` 的存储问题清单、每个 `query_id` 的检索排序、recall@k 与 MRR 与迁移前逐项一致。
   - world_script_execute：106 条用例的 `code`、`truth`、`pass` 与迁移前逐项一致（含失败用例的问题文字）。基线需真模拟器运行一次。
   - episode_vision_read：迁移前真跑一次旧 solver，保存每帧 `PerceiveRun` 与旧 `judge_facts` 的逐帧逐列 C/I/N 作基线；迁移后在验证脚本里把新 `truth_fields` / `field_verdict` 直接作用于同一批 `PerceiveRun`，逐项一致。这批产物至少覆盖全部默认帧，并含一个解析失败的帧（没有则合成一个）。这只是验收手段，不是产品功能。
2. 各指标 Total 符合：memory 三项均为 3；`code`、`truth` 为 106，`pass.<脚本>` 之和为 106；视觉各列 Total 等于该列的可判帧数（由基线统计出）。
3. 每个 B 类入口一条命令输出整体 Pass Rate 与 Aggregate Metrics，只列失败；有失败时退出码 1。
4. decode 改用 `common.run` 后，第一阶段验收（24035 个判定一致、23 个指标 Total、退出码）复跑通过。
5. `evals/solvers/`、`evals/scorers/`、`evals/tasks/` 不存在，`evals/dataset/` 只剩 `frames/`、`io.py`、`errors.py`；`evals.registry.TASKS` 恰好六项，每项入口存在。
6. C 类两个 task 在新路径下 `inspect eval ... --limit 1` 能装配并开始运行；任务名、Langfuse 的 run_id 命名、dataset 内容不变。
7. 全量 `pytest` 通过；`ruff check` 与 `ruff format --check` 通过。
8. 仓库内不再有旧路径的活引用（历史文档的说明性文字与 `CHANGELOG.md` 历史条目除外）。
9. 运行后工作区新增的未跟踪文件都已被 `.gitignore` 覆盖。

---

## 七、风险

- **R1 world_script_execute 的序列化。** `ScriptRun` 能否无损往返 JSON 是 §2.2 的前提；不通就走退路，并向用户报告。
- **R2 超时保护。** 原 300 秒上限由 Inspect 强制；进程隔离在 Windows 上有 `spawn` 的启动成本和 pickling 约束，可能影响单例耗时。需实测总耗时，与迁移前相比明显变慢要报告。
- **R3 视觉评测的费用与确定性。** 基线要真调一次视觉模型，验收时再用新入口真跑一次；温度虽为 0，两次输出仍可能略有不同，所以逐项对照用的是同一批保存下来的 `PerceiveRun`，不是两次独立运行的结果。基线文件需另存，因为 `eval_results/` 被忽略，存放位置由用户指定。
- **R4 工作区未提交改动**（P0）。
- **R5 路径常量。** `paths.py`、加载器里的数据路径、`pack.py` 和 `build/*.py` 里的相对路径、文档里的命令，凡写死 `evals/dataset/...` 的都要改；漏改会在运行时才暴露。验收 8 的 grep 要覆盖 `.py`、`.md`、`.toml`、`.json`。
- **R6 C 类移动量大。** `agent_short_goal_run` 的 `v1/states/` 与 `archives/` 文件很多，`git mv` 之后用 `git status` 确认全部识别为重命名。
- **R7 Windows 下的 `git mv`。** 大小写与长路径问题；失败要报告，不要手工复制再删除。

---

## 八、非目标

- 不改判定语义、数据、真值、被测代码，不换评审模型。
- 不新增任务（brain_choose_action、memory_poisoning_resistance 等仍待单独排期）。
- 不改 C 类的 scorer 与 solver 逻辑，只搬目录与改 import。
- 不引入 GEval 等需要 LLM 判分的指标；本阶段三个 B 类都是确定性判定。
- 不处理 `docs/eval/tasks-intent.md` 等历史计划文档的正文，只加标注。

---

## 九、交接清单（给执行者）

每步一个提交，提交信息遵循仓库现有格式；每个 S0 先于对应的删旧代码。

**P0（用户）**：提交或明确处理当前未提交改动。未完成就停止。

**S1 共享件**
1. 建 `evals/common/`，移入 `world_case.py`，新增 `run.py`（§1.1）。
2. 移 `evals/solvers/world_case.py` → `evals/common/world_case.py`，改 import。
3. decode 改用 `common.run`；复跑第一阶段验收。
4. 暂不动 `registry.py`。

**S2 memory_store_recall**
1. S0：用旧 `evaluate_memory` 与 `retrieval_metrics` 直接调用（不经 Inspect），导出 `eval_results/memory_baseline.json`。
2. 建 `evals/memory_store_recall/` 全部文件，入口跑通，与基线逐项对照。
3. 删旧 task、solver、scorer、dataset 对应文件，改测试与文档。

**S3 world_script_execute**
1. S0：用旧 `script_solver` 内核与 `judge_case`，在真模拟器上跑全部用例，导出 `eval_results/script_baseline.json`（`case_id`、`code`、`truth`、`pass`、问题文字）。同时验证 `ScriptRun` JSON 往返后 `judge_case` 结果不变（R1）。
2. 建 `evals/world_script_execute/`，入口跑通，与基线逐项对照；实测总耗时并记录（R2）。
3. 删旧代码，改测试与文档。

**S4 episode_vision_read**
1. S0：真跑一次旧 solver，保存每帧 `PerceiveRun`；用旧 `judge_facts` 逐帧逐列导出 C/I/N，写入 `eval_results/vision_baseline.json`。**这一步会调视觉模型，开始前先确认费用可接受。**
2. 建 `evals/episode_vision_read/`，在验证脚本里用保存的 `PerceiveRun` 与基线逐项对照；再用入口真跑一次，确认并发、不通帧的提示和退出码。
3. 删旧代码，改测试与文档。

**S5 C 类与收尾**
1. 迁 `brain_goal_judge`、`agent_short_goal_run` 到新布局（§3.1），只改 import；两个 task 各跑 `--limit 1` 装配检查。
2. 建 `evals/registry.py`，删 `evals/tasks/`、`evals/solvers/`、`evals/scorers/`，清掉 `evals/dataset/` 里已搬走的任务子目录。
3. 同步 `AGENTS.md`、`CLAUDE.md`、`SPEC.md`、`tasks-spec.md`；`CHANGELOG.md` 加条目；全仓 grep 旧路径。

**停止条件**：任一 S0 自检与预期不符、`ScriptRun` 无法往返、超时保护无合适方案、`git mv` 未被识别为重命名、等价对照出现任何不一致——停下来报告，不要改比较规则去"凑一致"。

**完成条件**：验收 1–9 全部满足，CHANGELOG 写明口径变化（§五）。
