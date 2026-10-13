# spec —— decode 迁到 B 类：DeepEval `evaluate()` 启动、逐字段指标、DeepEval 汇总

> 流程位置：eval-split-intent.md → **eval-split-spec.md** → plan → PR → production
> 依据：`docs/eval/eval-split-intent.md` v6 第八节；现状以 2026-10-12 仓库为准（registry 六个 inspect task；`pyproject.toml` dev 组已含 `deepeval>=4.2.8`，已装入 `.venv`）
> 状态：**已实施，验收通过**（S0–S3 对应 CHANGELOG 430–433；2026-10-13 校正已删除 CLI 的验收要求；第二阶段后使用 common.run 与根级 registry）。
> 范围：**只含 decode**。其他 B 类任务各自另起 spec，复用本文定下的目录规则、`Verdict` 与"一状态一用例、一字段一指标"的做法。
> 顺序：S0 先固化旧实现的逐 (帧, 字段) 判定结果 → S1 抽出纯逻辑 → S2 DeepEval 入口与指标 → S3 删旧 task、删基线脚本、文档同步。每步一条 CHANGELOG 编号条目，独立 commit。

---

## 〇、暂定项（按推荐写入，可推翻）

| 编号 | 暂定方案 | 影响小节 |
|---|---|---|
| D1 | 目录规则：`evals/<任务名>/`，任务自己的 dataset、solver、scorer 放进同一目录；decode → `evals/decode/`。取代 `docs/eval/tasks-spec.md` §1.4 的槽位规则；其他任务迁移前保持原位。共用的 `evals/dataset/frames/` 暂留原位，decode 从它加载 | §二 |
| D2 | 不用 pytest。入口是普通 Python 命令，调用 `deepeval.evaluate()` | §三 |
| D3 | 一帧一个 `LLMTestCase`；`actual_output` 放整帧解码结果的 JSON，`expected_output` 放整帧真值的 JSON；每个真值字段一个指标，指标名 `组.字段` | §一 |
| D4 | 只有一种情形不挂指标：真值里没有该键（未标注）。真值为空（`None`、`""`、`[]`）算已标注，照常计分，`False`、`0` 同理 | §一 |
| D5 | 不设 `--include-empty` 之类开关；真值为空时 decoder 输出了内容算失败，保留原有的"乱输出"检查 | §一、§三 |
| D6 | 统计全部用 DeepEval 原生输出：整体 Pass Rate（帧级）+ Aggregate Metrics 表（逐字段通过率与计分数）；只显示失败的帧。不自写汇总表 | §三 |
| D7 | 不再单设"[非空]"之类派生指标；一个字段一个指标 | §一 |
| D8 | 有失败帧时入口退出码为 1，便于做回归检查 | §三 |
| D9 | 旧 inspect 代码与 `scripts/decoder_baseline.py` 一次性删除，不留兼容层 | §二 |

---

## 一、契约

**1.1 `decode_frame(sample) -> DecodeRun`**（搬自 `evals/solvers/decode.py`，逻辑不变）
前置：`sample.wram` 非空，保留原 `assert`。`DecodeRun` 四个字段组（scene / screen / takeover / terrain）与原模型一致；未加载地图的帧没有地形组。不再有 `DecodeRecord`、`decode_solver`。每帧只在构造用例时解码一次。

**1.2 `Verdict`**：`value: Literal["C","I","N"]`，`reason: str`。

**1.3 `field_verdict(got_group, truth_group, key) -> Verdict`**（由原 `compare_group` 拆成逐键，比较语义逐字不变）
- 真值组为空，或 `key` 不在真值组里 → `N`（未标注）。
- `key == "screen_contains"`：真值里每条文字都必须出现在 `got_group["screen"]`，缺哪条写进原因。
- 其他键：实际输出必须**含有该键**（区分"键不存在"与"值为 None"），且值相等；否则 `I`，原因写 `键: 实际 ≠ 期望`。真值为 `None`、`""`、`[]` 时同样照此比较，不特殊处理。
- `at_path`、`contains_path`、`truth_for` 一并搬入，逻辑不变；键可以是点路径。

**1.4 字段清单与计分帧数**（来自 `frames/v2/truth.jsonl` 实际数据，共 23 个字段）

| 组.字段 | 计分帧数 |
|---|---|
| scene.scene、scene.covered_by_script、scene.at_start | 1045 |
| screen.screen、dialog_text、options、option_grid、option_details、cursor、cursor_cell | 1045 |
| screen.covered、has_cursor、quantity_box、strict_dialog、in_battle、overlay | 1045 |
| screen.screen_contains | 8 |
| takeover.view（整体比较） | 1045 |
| terrain.map_id、where、facing | 1019 |
| terrain.walk_map、neighbors | 1018 |

这些数字是当前数据下的预期值，用于自检；字段清单**不硬编码**：入口扫描全部帧的真值键并集生成指标，与表不一致时以数据为准，并在测试里断言键并集等于上表。

**1.5 指标 `FieldMatch(BaseMetric)`**
- `__init__(self, name: str, group: str, key: str, threshold: float = 1.0)`，**每个构造参数都以同名属性保存**（DeepEval 按参数名复制指标，否则 `TypeError`）。`name` 形如 `screen.options`。
- `measure`：反序列化 `actual_output` / `expected_output`，调 `field_verdict`；返回 `N` 时抛 `MissingTestCaseParamsError`（该指标在该用例上被跳过）；`C` → score 1.0，`I` → 0.0，`reason` 取 `Verdict.reason`。
- 不调 LLM：`evaluation_model = None`，`async_mode = False`。

**1.6 `evaluate()` 调用**
- `test_cases`：每帧一个，`input` 为 `sample_id`。
- `metrics`：23 个字段指标，应用于所有用例。
- `ErrorConfig(skip_on_missing_params=True, ignore_errors=False)`；`AsyncConfig(run_async=False)`；`DisplayConfig(print_results=True, display_option=FAILING, results_folder="eval_results/decode")`。
- `hyperparameters={"dataset": "frames/v2", "frames": <数据集帧数>}`，同时消除 DeepEval 的 "No hyperparameters logged" 提示。
- 共享运行器开头设置 `DEEPEVAL_TELEMETRY_OPT_OUT=YES`，保证无遥测。

---

## 二、目录与改动清单

**新增**

```
evals/decode/
├── __init__.py     # 出口：decode_frame、field_verdict、Verdict、FieldMatch、build_cases、build_metrics
├── __main__.py     # 入口：python -m evals.decode
├── dataset.py      # 从 evals.dataset.frames 读冻结帧 → LLMTestCase
├── solver.py       # DecodeRun、decode_frame
├── compare.py      # Verdict、field_verdict、at_path、contains_path、truth_for（不依赖 deepeval）
└── scorer.py       # FieldMatch、build_metrics
```

**删除**：`evals/tasks/decode/`、`evals/solvers/decode.py`、`evals/scorers/decode.py`、`scripts/decoder_baseline.py`。`judged_accuracy` / `judged_count` 仍被其他 task 使用，保留。`evals/dataset/frames/` 保留（episode_vision_read 共用）。

**修改（代码与测试）**

| 文件 | 改动 |
|---|---|
| `evals/tasks/registry.py` | 去掉 decode；docstring "六个"→"五个" |
| `evals/cli.py`、`evals/__main__.py` | 已于独立的入口收敛工作中有意删除；本次不恢复，不要求修改措辞或执行 `python -m evals list` |
| `tests/test_evals_tasks.py` | 改 import；`test_generic_decoder_metrics_…` 原依赖 inspect 运行，改为直接测 `field_verdict`（含缺键为 N、真值为空照常比较、`None` 值要求键存在）；`test_only_the_six_…` 改为五个 |
| `tests/test_evals_datasets.py` | `test_all_six_tasks_assemble_…` 参数表去掉 decode，改名为 five |
| `tests/test_evals_perceive.py` | `decode_frame` 的 import 路径；用到 `compare_group` 处改为 `field_verdict` |
| `.gitignore` | 加 `.deepeval/` 与 `eval_results/decode/` |

**修改（文档与引用）**

| 文件 | 位置 | 改动 |
|---|---|---|
| `AGENTS.md`、`CLAUDE.md` | 第 555、557 行 | 公开 inspect task 由六个改五个；decode 改述为 B 类，由 DeepEval 逐字段汇总；两份逐字同步 |
| `docs/spec/evals/SPEC.md` | task 表、decode 段、`baseline_only` 段（约 105–106 行）、命令清单（约 116 行）、标注覆盖段 | 改为 B 类描述与新命令；删除 `baseline_only` 说明；新增"B 类运行方式"与"目录规则"两节 |
| `docs/eval/tasks-spec.md` | §1.4 槽位规则 | 追加一句注："2026-10-12 起槽位规则被 `eval-split-intent.md` 的目录规则取代，按任务逐个迁移"，原文保留 |
| `docs/DECODER_FIX_1007.md` | 第 82、92 行 | 已于 2026-10-12 追加说明，不要改动 |
| `docs/PLAN_decoder_truth_fix_1008.md` | 第 19、134、135 行 | 已于 2026-10-12 追加说明，不要改动 |
| `CHANGELOG.md` | 新增条目 | 记录迁移原因与口径变化；不改历史条目 |

默认 `pytest` 的 `testpaths = ["tests"]`，不收集 `evals/decode/`。

---

## 三、运行方式

```powershell
# 全量：整体 Pass Rate + 逐字段 Aggregate Metrics，只显示失败的帧
python -m evals.decode

# 只看某些帧或某个场合（排查用）
python -m evals.decode --frame p-option_screen --frame c-0419
python -m evals.decode --scene bag
```

- `--frame` 可重复，`--scene` 按真值里的场合筛选，均在构造用例前过滤。
- 有失败帧时退出码为 1，否则为 0。
- 每次运行在 `eval_results/decode/` 下留一份 DeepEval 的 `test_run_<时间>.json`，两次运行的结果对比用它。

---

## 四、口径

**不变：**
- 判定语义：逐键比较，只比有标注的键；键存在性与 `None` 值的区分；`screen_contains` 逐条核对。
- 参考真值只读 `frames/v2/truth.jsonl` 挂载的独立标注，不读被测解码输出。
- 只取带 WRAM 的帧（现为全部 1045 帧）。
- 不启动模拟器，不调 LLM，不需要网络。

**有意调整：**
- 原"四组 `C/(C+I)`"改为"逐字段通过率与计分数"。组内"所有键都对才算 C"的组级数字不再单独出，需要时从逐字段结果推。
- 新增帧级通过率（一帧所有已计分字段都对才通过），分母是至少有一个已计分字段的帧。
- 空值字段照常计分，"本应为空却输出了内容"仍算失败，与原行为一致。
- 原基线脚本的"场合分布"改为入口的 `--scene` 过滤；"fixed / regressed"对比暂无，以后用 `results_folder` 的两份导出对比失败帧。

---

## 五、验收

1. **逐项等价（S0 先做）**：删旧代码之前，用旧的 `compare_group` 逻辑对全部帧按键拆开，导出每个 (sample_id, 组, 键) 的 C / I / N 与"真值是否为空"到 `eval_results/decode_baseline_1012.json`（独立于 DeepEval，不改被测逻辑）。迁移后：
   每个 (帧, 字段) 的"通过 / 失败 / 未挂指标"与基线中 C / I / N 逐项一致。
2. 一条命令输出整体 Pass Rate 与 23 行 Aggregate Metrics；`display_option=FAILING` 时只列失败帧。
3. 各指标的 Total 等于 §1.4 的计分帧数。
4. 检查 `evals/registry.py` 的 `TASKS` 恰好为六个公开任务（四个 DeepEval、两个 Inspect），由 `test_only_the_six_evaluation_tasks_are_public` 核对键集合与入口函数；`test_evals_tasks.py`、`test_evals_datasets.py`、`test_evals_perceive.py` 与全量 `pytest` 通过。旧 CLI 已有意删除，不执行 `python -m evals list`。
5. `--frame`、`--scene` 有效，失败时退出码为 1。
6. 运行后工作区新增的未跟踪文件都已被 `.gitignore` 覆盖。
7. 仓库内不再有对 `scripts/decoder_baseline.py`、`evals.solvers.decode`、`evals.scorers.decode`、`baseline_only` 的活引用（历史文档的说明性文字与 `CHANGELOG.md` 历史条目除外）。

---

## 六、已验证事实（隔离环境，deepeval 4.2.8，Python 3.12）

- `evaluate(print_results=True)` 除整体 Pass Rate 外，会打印 **Aggregate Metrics** 表：每个指标的平均分、通过率（含 passed / failed）与 Total。`print_results=False` 时只有整体 Pass Rate。
- 指标检测到缺失参数时抛 `MissingTestCaseParamsError`，配合 `skip_on_missing_params=True`，该指标在该用例上被丢弃，不计入该指标的 Total。
- 每个用例的结果在 `result.test_results[i].metrics_data` 里，含指标名、是否通过、分数与原因。
- DeepEval 复制指标时按 `__init__` 参数名取同名实例属性，不同名会 `TypeError`。
- `DisplayConfig` 有 `display_option`（`ALL` / `FAILING` / `PASSING`）与 `results_folder`。
- 运行会在当前目录写 `.deepeval/` 下的缓存与运行记录。
- 仅验证到 4 个用例 × 2 个指标的规模。

## 七、待验证 / 风险

- **规模**：1045 个用例 × 23 个指标。探针规模太小，实际耗时与内存未测，S2 先量；若 `run_async=False` 太慢，再试 `True`。
- **`display_option=FAILING` 的实际输出**：配置项存在，但还没用它跑过，S2 先看输出是否只含失败帧。
- **"缺参数即跳过"依赖 DeepEval 行为**：这是借异常做控制流。S0 的逐项等价检查就是防它在版本升级后悄悄变化。
- **共用数据暂留原位**：`evals/dataset/frames/` 不随 decode 迁移，decode 对它保持只读依赖；归属在 episode_vision_read 迁移时再定。
- **`.deepeval/` 与 `results_folder` 的落点**：S2 跑一次后看实际新增文件，再定 `.gitignore`。
- **takeover.view 整体比较**：失败时原因里是整个嵌套结构的差异，可读性可能差，S2 看后再定是否展开。

## 八、非目标

- 不改解码逻辑、真值、帧集、`judged_accuracy` 口径。
- 不迁移其他任务，不移动 `evals/dataset/frames/`。
- 不引入 DeepEval 的 LLM 指标；decode 全程确定性。
- 不做 fixed / regressed 对比工具，也不保留 `baseline_only` 开关。

---

## 九、执行清单（交接）

**前置**：在仓库根目录用项目 `.venv` 运行（Windows：`.venv\Scripts\python`）；`deepeval>=4.2.8` 已装。每步独立 commit，各配一条 CHANGELOG 编号条目（取现行编号的下一个），写明变更原因。不改被测系统代码。测试用例加进现有测试文件，不新建。

**停止条件**：出现下列任一情况，立即停下并报告，不要自行绕过——S0 导出的基线里有任何 `I`；新旧逐项比对出现不一致；DeepEval 的"缺参数即跳过"行为与 §六不符。

**S0 固化基线**（一次性脚本，不入库）
1. 用现有 `decode_frame` 与旧 `compare_group` 的逐键规则（`at_path` / `contains_path` / `screen_contains`），对 `frames/v2` 全部帧导出 `eval_results/decode_baseline_1012.json`：列表，元素 `{"sample_id", "group", "key", "verdict"}`，`verdict` 取 `C` / `I` / `N`（`N` 指该帧该组无标注或真值里没有该键）。键集合为各组真值键的并集（23 个）。
2. 同时汇总每个键的 C / I / N 个数。
3. 自检：`I` 应为 0（现有文档记录完整诊断全为 C）；`terrain.map_id`、`where`、`facing` 的 N 为 26，`walk_map`、`neighbors` 的 N 为 27，`screen_contains` 的 N 为 1037；每个键的 C+I 个数应与 §1.4 一致。

**S1 抽出纯逻辑**
1. 建 `evals/decode/{__init__,solver,compare}.py`，按 §一的 1.1–1.3 搬入 `decode_frame`、`Verdict`、`field_verdict` 与路径工具；比较语义不变。
2. 旧 `evals/solvers/decode.py`、`evals/scorers/decode.py` 暂改为从新包导入（仅为让旧 task 与旧测试在 S3 前继续通过，S3 删除）。
3. 在现有测试里加 `field_verdict` 用例：缺键为 N、空值与 `None` 照常比较且要求键存在、`screen_contains` 缺哪条写进原因。
4. 完成条件：旧 inspect `decode` 的计数与 S0 基线一致；相关现有测试通过。

**S2 DeepEval 入口与指标**
1. 建 `dataset.py`、`scorer.py`、`__main__.py`，按 §一的 1.4–1.6 实现；`FieldMatch` 的构造参数必须以同名属性保存。
2. 在现有测试里加：键并集等于 §1.4 的 23 个字段；仅未标注不挂指标，空值挂指标。
3. 运行 `python -m evals.decode`，核对验收 1、2、3、5，并记录耗时。`display_option=FAILING` 的实际输出与 1045 × 23 的耗时若不符合预期，如实写进 CHANGELOG；耗时过长再试 `run_async=True`。
4. 新旧逐项比对：把 DeepEval 的 `result.test_results`（或 `eval_results/decode/` 下导出的 `test_run_*.json`）展开为 (sample_id, 字段, 通过 / 失败 / 未挂指标)，按验收 1 的两种口径与 S0 基线逐项比对，必须完全一致；比对脚本不入库。

**S3 删旧与同步**
1. 删除 `evals/tasks/decode/`、`evals/solvers/decode.py`、`evals/scorers/decode.py`、`scripts/decoder_baseline.py`。
2. 按 §二的"修改"两张表改代码、测试与文档（含 `AGENTS.md` 与 `CLAUDE.md` 两份逐字同步、`docs/spec/evals/SPEC.md`、`docs/eval/tasks-spec.md` 的追加注、`.gitignore`、`CHANGELOG.md` 新条目）。历史文档的两处说明已追加，不要改动。
3. 跑 `ruff check . && ruff format .` 与全量 `pytest`。
4. 按验收 4、6、7 收尾：根级 registry 的 `TASKS` 恰好为六个公开任务，公开任务契约测试通过；仓库内无对旧模块、基线脚本与 `baseline_only` 的活引用。不恢复已删除的 `evals/cli.py` 或 `evals/__main__.py`。

**完成条件**：验收 1–7 全部满足，并在最后一条 CHANGELOG 中写明口径变化（四组 `C/(C+I)` → 逐字段通过率与帧级通过率）。
