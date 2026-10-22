# spec —— 递归规划二十例：合并采集、逐例标注与四个 Inspect 任务换版

> 流程位置：intent（已确认）→ **spec（本文）** → plan → 落码
> 依据：`docs/eval/brain-annotation-recursive-intent.md`；`docs/eval/brain-call-capture-spec.md`；`evals/dataset/brain_annotations/v2/REPORT.md`。
> 基线：`97ab011`（CHANGELOG 563）。分支 `evals/brain-annotation-recursive`。

## 一、决定

| 编号 | 决定 | 理由 |
|---|---|---|
| D1 | 新版本号 `V = v20261020_1846`，四族数据、标注旁账、四个任务默认值共用同一个号，一经发布不再改 | 用户 2026-10-20 要求统一起新号、按当时时间固定 |
| D2 | 14 例（`brain_capture_recursive_20261020`，HEAD `3ca4ecd`）与 6 例（`brain_capture_remaining6_20261020`，HEAD `97ab011`）并为一个集合；`DatasetManifest` 新增可选 `source_parts`，逐段记录批次、HEAD、代码哈希、schema 哈希、样本；`source_head` 取补采段 | 两段 schema 同为 `5d3630f2b479ee78`；562/563 不改脑的运行逻辑；混合 HEAD 如实记账，不伪装成单一提交 |
| D3 | 合并以两份已核验的导出（各自带 `sources.zip`）为输入，不重新导出批次；合并后对整份集合重跑 `verify` | 导出已在原机通过来源哈希与请求重读核验；VM 不能解析批次报告里的 Windows 绝对路径 |
| D4 | 标注作者表放数据文件，不放 Python 字典：`evals/dataset/brain_annotations/authoring/V/{choose,plan,decompose,judge}.jsonl`，一行一个 `case_id`；构建器逐例要求登记，缺登记或多登记直接失败 | 沿用「未登记失败关闭」；370 条放进代码字典不可读 |
| D5 | `Annotation` 增加可选 `expected_decision`（仅 judge），与 `achieved` 一致；旧 v1/v2 旁账不变、哈希不变 | 561 之后 judge 是四类结论，`decision_summary` 只统计带该字段的样本 |
| D6 | judge 的机械标签沿用原规则（`visible_judge` 与登记判据），人工标注只补机械规则不覆盖的样本；`expected_decision` 只在独立证据足以区分时写 | 不凭猜测补 `blocked` / `interrupted` |
| D7 | choose / plan / decompose 沿用 `advisory_v1`：三维 criteria 与 `criteria_for` 完全复用；每例只写 `rationale`、`suggestions`，choose 另写 `acceptable`（建议动作，不是白名单） | 与 2026-10-20 口径一致；v4/v3 的 grader 无需改 |
| D8 | choose 里已有独立机械动作集合的 15 条（`action_set`）继续保留其动作集合，并并入建议；其余 107 条由人工写建议 | `choose_reference` 已有规则，不重造 |
| D9 | 状态为 `invalid_task` / `unjudgeable` 的条目不进分母，逐条列入 `coverage.json`，同旧版做法 | 排除项不得伪装成负标签 |
| D10 | 旧版本（`brain_calls/v1`、`brain_annotations/v1,v2`、choose v1–v4、plan v1–v3、decompose v1–v3、judge v1–v4）原样保留，字节不变 | 用户：旧版本留档作参考 |
| D11 | 工作在独立分支；CHANGELOG 取号 565–567（564 已被 Graphiti 探针占用），合入时若编号冲突由设计侧重编 | 并行任务台账已过期，主工作区 CHANGELOG 有未提交修改 |

## 二、数据流

```
batch A (14, 3ca4ecd) ─export→ partA/v2 ┐
batch B ( 6, 97ab011) ─export→ partB/v2 ┴─ merge_exports → brain_calls/V/{judge,plan,decompose,choose,summary}
                                                              + collection.json + sources.zip(+manifest)
brain_calls/V ─ authoring/V/*.jsonl + 机械引用 ─ recursive_build → brain_annotations/V/{choose,plan,decompose,judge}.jsonl + manifest.json
brain_annotations/V + brain_calls/V ─ publish_recursive → brain_{choose,plan,decompose,judge}/V/
```

## 三、模块与改动

### 3.1 合并（`evals/dataset/brain_calls/merge_exports.py`，新增）

- `merge(parts: list[Path], output: Path, version: str)`：`output` 必须不存在。
- 样本顺序取 `load_samples()` 顺序；同一样本内保持各自导出顺序。`case_id` 全局唯一，重复即失败。
- 逐族拼接 `inputs.jsonl` / `references.jsonl`，复制两段一致的 `*.request.schema.json`（字节不一致则失败）。
- 逐族重写 `manifest.json`：`version=V`、`cases`、`layers`、`baseline_status`、`mechanical_labels`、`action_set_labels`、`rubric_cases`、`files_sha256` 全部按合并结果重算；`source_parts` 逐段登记；`limitations` 中的数量改为二十。
- 合并 `sources.zip` 与 `sources.manifest.json`：条目取并集，同名不同哈希则失败。
- 合并 `collection.json`（`partial=false`、`expected=20`、`completed=20`、`sample_ids` 二十个、`batches` 两段）、`scope_warnings.json`、`skipped_calls.jsonl/summary.json`。
- 产出后调用既有 `verify(output)`。
- `DatasetManifest.source_parts: list[SourcePart] = []`（默认空，旧 manifest 读写不变）。

### 3.2 标注契约与构建（`evals/dataset/brain_annotations/`）

- `contract.py`：`Annotation.expected_decision`（可选，只允许 judge；`achieved` 与之一致；`interrupted` 仅在请求 `allow_interrupt` 时允许）。
- `authoring.py`（新增）：读取 `authoring/V/<family>.jsonl`，行模型 `Authored`：`case_id`、`status`（`labelled/invalid_task/unjudgeable`）、`rationale`、`suggestions`、`acceptable`（choose）、`achieved` / `expected_decision`（judge）。多余、缺失、重复均失败。
- `recursive_build.py`（新增）：对每族每例：
  - judge：参考为机械标签 → `mechanical_preexisting`（保留 `check_id` 与原因）；否则取作者表 → `codex_history_review`。
  - choose / plan / decompose：生成 `evaluation_mode="advisory"`，`criteria=criteria_for(case)`，`evidence=collect(case)`，其余取自作者表；choose 若有机械 `action_set`，其动作集合并入 `acceptable`。
  - 写 `brain_annotations/V/<family>.jsonl` 与带哈希的 `manifest.json`（`collection_version=V`，`baseline_answers_used=false`）。
- 证据只来自请求（沿用 `evidence.collect`）。`collect` 的指针名单需覆盖递归规划新增字段：`remaining_planning_rounds`、`execution_order`、`latest_planning`、`planning_round`、`trigger`、`goal_table`、`allow_interrupt`、`run_goal`。

### 3.3 发布与加载

- `publish_recursive.py`（新增）：生成
  - `brain_choose/V`、`brain_plan/V`、`brain_decompose/V`：`manifest.json`（`collection_version=V`、`annotation_version=V`、输入/参考/旁账哈希）+ `coverage.json`；
  - `brain_judge/V`：`dataset.jsonl`（`JudgeCaseV3`，写 `expected_decision`）+ `manifest.json` + `coverage.json`。
- `brain_judge/loader.py`：`_VERSION_MODELS` 增加 `V → JudgeCaseV3`。
- 四个 `task.py` 默认 `version` 改为 `V`；`brain_choose` 的旧 DeepEval 入口与 legacy 诊断不动。
- `evals/dataset/brain_annotations/V/REPORT.md` 与 `evals/dataset/brain_calls/V/REPORT.md`：条数、排除项、两个 HEAD、控制账、与上一版差异。

### 3.4 scorer 适配（只做必要的）

- `brain_plan/compare.py` 与 `brain_decompose/compare.py` 的结构检查在新请求上跑通；若 `max_push`、`plan` 等字段在新请求中语义变化，只改读取处，并补一条新语义结构项的测试，不改建议式质量分口径。
- `judge_scorer` 与 `decision_summary` 不改；`brain_judge` 的 `V` 数据带 `expected_decision` 的样本进入四类矩阵。

## 四、标注规则

**通用**：只用该调用请求里的内容；不读旧响应、后续调用、整局结果；`last_judge`、`latest_planning` 属于请求，可作为现场事实引用，但其结论是主张，不是证据。

**judge**

1. 先看机械标签；有则保留。
2. 无机械标签：按判据类型（状态型 / 事件型 / 跨帧比较型 / 或型）在请求的当前观测与历史里找证据，写 `achieved` 与一句依据，引用具体字段。
3. `expected_decision`：达成 → `achieved`；未达成且本层动作仍能推进 → `continue`；请求里有具体阻塞条件且本层无法解决 → `blocked`；`interrupted` 只在 task 层 `allow_interrupt` 且请求显示出现了未预料的战斗/剧情/传送时标。拿不准就不写，保留二元标签。
4. 目标、判据自相矛盾或现场无法判断 → `unjudgeable`，不进分母。

**choose**

- `acceptable`：当前动作空间里启用的、一步内合理推进目标或合理纠偏的按键 / 脚本；失败后的探索写入 `suggestions`。不得把越过目标的确认键（目标只要求光标到位时的 `a`）列为建议。
- 上游子任务本身错误（前提失效）时，允许转向正确交互对象；仍标 `labelled`，把纠偏写入 `rationale`。
- 现有能力无法表达上层结算（例如光标已满足目标但无 stop）→ `invalid_task`。

**plan / decompose**

- `rationale`：当前现场与目标；`suggestions`：必要前置、已满足步骤、禁止项、预算与轮次约束的建议路线，措辞不作唯一模板。
- 空新增合法：当父目标已达成、或现有待办足以推进时，建议里写明可以不新增。
- 原目标含禁止条款而现场已违反 → 建议写明可通过 `why` / `note` / `abandoned` 说明阻塞，不发明违禁步骤。

## 五、验收（机械可验）

1. `brain_calls/V` 每族条数 = 两段之和：judge 183、plan 21、decompose 41、choose 122、summary 81；样本 20；`verify` 通过。
2. 四族标注逐条与输入一一配对，`load(family, V)` 的证据哈希全部通过；缺登记、重复、未知 `case_id` 均失败。
3. `coverage.json` 列出全部排除项及原因；`labelled + excluded = 源条数`。
4. 旧版本目录字节与基线一致（`git diff --stat 97ab011 -- <旧路径>` 为空）。
5. 四个任务在 Fake 被测模型 + Fake grader（或 `grader_model=none`）下以默认版本跑通；plan / decompose 的结构检查在新请求上无异常。
6. 新增测试覆盖：合并（顺序、去重、哈希、拒绝冲突）、`Annotation` 新字段约束、构建器失败关闭、加载器哈希核验、judge `expected_decision` 进入四类矩阵。`pytest` 与 `ruff check` / `ruff format --check` 通过；所有提交用 LF。
7. 不调用真实模型。

## 六、风险

- 作者表量大（约 370 条）：按场景分批写，每批用同一脚本回读核对 `case_id` 覆盖。
- `invalid_task` 比例过高会缩小分母：报告里列出，不为凑数改标。
- 合并导出的 `limitations`、`collection.json` 与单段导出字段不同，下游只读 `inputs/references/manifest`，不依赖这些字段。
