# plan —— 递归规划二十例标注与换版

> 依据：`docs/eval/brain-annotation-recursive-spec.md`。分支 `evals/brain-annotation-recursive`，基线 `97ab011`。
> 版本号 `V = v20261020_1846`。CHANGELOG 取号 565–567，逐检查点一条，提交标题逐字复用条目标题。
> 沙箱事实：VM 无法解析批次报告里的 Windows 绝对路径，故合并只读已导出数据；全部命令在 `/tmp/venv`（Python 3.11）中运行，不调用真实模型。

## 检查点

| CP | CHANGELOG | 内容 | 退出条件 |
|---|---|---|---|
| CP1 | 565 | `DatasetManifest.source_parts`；`merge_exports.py`；生成 `brain_calls/V`（二十例）；合并测试 | `verify` 通过；条数为 judge 183 / plan 21 / decompose 41 / choose 122 / summary 81；旧版本字节不变 |
| CP2 | 566 | `Annotation.expected_decision`；`authoring.py`、`recursive_build.py`；作者表 `authoring/V/*.jsonl`（choose、plan、decompose、judge）；`brain_annotations/V`；构建与加载测试 | 四族逐条登记；`load(family, V)` 通过；失败关闭测试通过 |
| CP3 | 567 | `publish_recursive.py`；`brain_{choose,plan,decompose,judge}/V`；judge loader 与四个 `task.py` 默认值；scorer 适配与测试；两份 REPORT；Fake 模型跑通 | 四任务默认版本在 Fake 下跑通；`pytest`、`ruff` 通过；旧版本字节不变 |

## 步骤

**CP1**
1. 在 `dataset_contract.py` 加 `SourcePart` 与 `DatasetManifest.source_parts`（默认空）。
2. 写 `merge_exports.py`；先对两份导出做干跑，打印每族条数与样本顺序。
3. 生成 `evals/dataset/brain_calls/V/`；跑 `verify_dataset`。
4. 写 `tests/evals/test_merge_exports.py`（用小型假导出：顺序、重复 `case_id`、schema 不一致、sources 冲突、manifest 重算）。
5. CHANGELOG 565，commit。

**CP2**
1. 写渲染脚本（只读请求，输出一例的目标、判据、现场、历史摘要），按场景分批阅读。
2. 写 `authoring/V/judge.jsonl`：先列机械标签覆盖，再逐条审其余；写 `choose.jsonl`、`plan.jsonl`、`decompose.jsonl`。
3. 加契约字段与两个模块；`build` 出 `brain_annotations/V`。
4. 一致性核对：覆盖、重复、`achieved` 与 `expected_decision`、choose 建议动作均在该次动作空间内启用。
5. 测试（失败关闭、字段约束、哈希），CHANGELOG 566，commit。

**CP3**
1. `publish_recursive.py` 生成四个任务数据目录；judge loader 登记 `V`。
2. 改四个 `task.py` 默认 `version`；核 plan / decompose 结构检查在新请求上的行为，必要时窄改。
3. Fake 被测模型 + `grader_model=none` 跑四个任务；用 Fake grader 验证质量分路径。
4. 写两份 `REPORT.md`；全量 `pytest`、`ruff`；对旧版本路径做字节差异检查。
5. CHANGELOG 567，commit；把分支推回主仓库（不改主工作区文件）。

## 停止条件

- 任一校验与既有旧版本字节冲突 → 停，不改旧版本。
- 发现采集数据本身缺账或请求与导出不一致 → 停，报告。
- 作者表中 `unjudgeable` + `invalid_task` 超过某族条数的三成 → 停，向用户汇报后再继续。
