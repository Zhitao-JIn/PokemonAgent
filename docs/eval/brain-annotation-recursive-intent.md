# intent —— 递归规划二十例：逐例标注并替换四个 Inspect 脑能力任务的数据版本

> 状态：已确认（2026-10-20）。流程：intent → spec → plan → 落码。

## 一句话意图

用递归规划（561）之后采集的二十例，重新逐例标注 choose / plan / decompose / judge，发布为一个统一的新数据版本，并让四个 Inspect 任务默认指向它。标注口径与评分口径沿用 2026-10-20 建议式约定，只做递归规划所需的适配。

## 要点

- 二十例 = 原批次十四例（`3ca4ecd`）+ 补采六例（`97ab011`），并为一个版本；两个提交如实登记。
- 新版本号 `v20261020_1846`，四族数据、标注旁账、四个任务默认值共用，一经发布不再改。
- 旧版本（`brain_calls/v1`、`brain_annotations/v1,v2`、choose v1–v4、plan v1–v3、decompose v1–v3、judge v1–v4）原样留档，字节不变。
- 标注只依据该调用自己的请求证据，不使用被测模型的旧响应、后续调用或整局结果。
- choose / plan / decompose：建议式参考 + AI 三维质量分（`state_and_scope` / `progress_or_recovery` / `boundaries_and_history`）+ 机械结构检查，分开展示。
- judge：独立标注「已达成 / 未达成」；证据足以区分时另写 `expected_decision`（achieved / continue / blocked / interrupted），进入四类矩阵，其余只保留二元标签。
- 不重采、不改被测模型、不改评分的建议式口径、不动 summary、不调用真实模型。

## 成功的样子

- 新版本覆盖二十个样本：judge 183、plan 21、decompose 41、choose 122；排除项显式列出，不进分母。
- 每条标注可追溯到它自己的请求证据；报告写明两个采集提交与 1 条预算控制账。
- 四个任务在 Fake 模型下以默认版本跑通；`pytest`、`ruff` 通过；旧版本字节未变。
