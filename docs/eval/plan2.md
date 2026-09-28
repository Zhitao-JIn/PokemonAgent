# plan2 —— evals 骨架重映射落地（inspect-ai 真依赖轻用）

> 流程位置：intent.md → spec2.md → **plan2.md** → PR → production
> 依据：`docs/eval/spec2.md`（09-28 定稿：真依赖轻用、观测三层分工、solver 子进程隔离、五步实现顺序）｜ 起草：2026-09-28 ｜ 状态：**草案，待确认**（§四 D5–D7）

---

## 〇、排序原则

1. **先冒烟、后搬迁**：R0 先用最小 @task 验证 inspect-ai 的 API 形状（Task/Solver/Scorer 真签名、`inspect view` 在本机能起），R2 的大搬迁不盲动。
2. **先契约、后消费**：R1 定 RunResult，R2 的 scorer 才有稳定输入——两步不许并作一步。
3. **每步独立可验**：结束时 pytest 全绿（带全新 `--basetemp`）+ ruff 干净；真机跑批交你本机 PowerShell 起（二号条）。
4. **每步 = 一条 CHANGELOG 编号条目**；被测系统（R1 动 `pokemon_agent/`）与 evals（R2 起）分开提交；commit 等你说再做。
5. **测试新增只写三类**（其余随迁移搬）：RunResult 往返、scorer 协议适配、evalset 的 epoch/resume 行为；要加别的先问。
6. evals 不进被测系统 import（E3 原则不变）；trace 读侧只经 `tools/trace/parse.py`（259 已落）。

## 一、步骤总览

| 步 | 内容 | 改谁 | 依赖 | spec 条款 |
|---|---|---|---|---|
| R0 | 探测：装 inspect-ai + 最小 @task 冒烟 + `inspect view` 本机验证 | pyproject、无代码 | — | fork #1 |
| R1 | RunResult：harness 返回值结构化（V8） | pokemon_agent/harness、schemas | R0 | §五 |
| R2a | 骨架搬迁：data/ 预打包（V1）+ core/bridge/tasks/scorers 建骨架 + 旧目录搬家 + 边界修正两处 | evals | R1 | §二、§五 |
| R2b | Scorer 收敛（V3）：三协议归一 + judge 一致性挂附加 scorer + 判定主输入换 RunResult | evals | R2a | §六 |
| R3 | eval_set 化（V2）：epochs / retry / resume / run_id 后缀 | evals | R2b | §一、取舍 A |
| R4 | manifest 扩展（V9）：EvalLog header + diff 校验扩字段 | evals | R3 | §七 |
| R5 | Metric 化（V7）+ 退役 report 渲染 + 活文档 | evals、docs | R4 | §一、§十 |

---

## R0 探测（不改 evals 代码）

1. `pyproject.toml` 加 `inspect-ai`（先装最新，`uv lock` 定版；版本号回填进 spec2 §〇）；`uv sync` 进 `.venv`。
2. **最小 @task 冒烟**（临时脚本，不进 evals/）：一个假 solver（返回固定结果）+ 一个 scorer + eval_set 跑两条假样本，产物落 `.eval`——核对 Task/Solver/Scorer/eval_set 的真实签名与 spec2 假设一致，不一致处回写 spec2。
3. **`inspect view` 本机验证**：打开第 2 条的 `.eval`，确认 Windows 本机起服务、总览页与 sample 钻取可用。
4. 顺带核：inspect-ai 的依赖清单（是否拉起冲突版本）；Solver 的返回类型里 metadata 放什么形状最省（供 bridge 定形）。

**验收**：冒烟脚本跑通、View 可看；API 偏差点（若有）回写 spec2。不通过则回到 fork #1 重议（借概念自研），后续步骤作废。

## R1 RunResult（V8）—— 唯一动被测系统的步

- **新模型** `pokemon_agent/schemas/harness/domain/run_io.py`：`RunResult`，字段 = `run_id` / `sample_id` / `outcomes: list[EpisodeOutput]`（原样复用，termination / judge_reason / acts_used / tasks_used 都已在）/ `total` / `succeeded` / `success_rate` / `usage`（分链路 input/output/cached/reasoning token、调用次数、`call_failed` 次数）/ `wallclock`（run 起止 ts）/ `episode_bounds`（逐局首末事件 uuid，供可选交叉核对定位）。
- **三处签名**：`harness/run/harness.py:79`、`checkpoint/restore.py:69`（restore_run）、`:131`（resume）——四元组 → `RunResult`。旧四元组的唯一解包点 `real_check/check_harness.py:369` 同步适配。
- **usage 聚合在 harness 内做**：run 收尾时 `deps.trace.read_events` 过滤 `_call` 账聚合——eval 从此不读 trace 拿统计（harness 本来就有 trace 权限，不算违规）。
- `sample_id` 由调用方传入（`RunHarness.run` / `restore_run` 加可选参，缺省空串——check_checkpoint / real_check 不受影响）。
- `one.py`：接 `restore_run` 返回的 `RunResult` 落盘 `run_result.json`（与 `run.json` 同目录）；`_record` 扩展。
- 测试：RunResult 构造 → `model_dump_json` → 读回字段相等（往返一条）；usage 聚合用合成事件流一条。

**验收**：定向（harness / checkpoint / real_check / 新测试）+ 全量 pytest 绿；ruff 干净。真机行为零变化（只是返回值换了形状）。

## R2a 骨架搬迁（行为不变）

- **目录**：建 `evals/core/`（六文件先 re-export 真协议 + 占位）、`bridge.py`、`tasks/`、`scorers/`、`data/`；旧 9 子目录按 spec2 迁移映射表搬文件、改 import、**搬完删旧目录**；`e2e/` 作为一个 task 的家（`tasks/e2e.py`）。
- **预打包（V1）**：一次性脚本把 20 state 打成 run_begin 存档进 `data/v1/checkpoints/<sample_id>/`（D5 定进不进 git）；`one.py::_pack` 改为读打包产物 + 哈希校验，不再现打包。
- **边界修正两处**：`screen_reading/observe.py:10-12` 停止 import 被测私有名（契约上移 `world` 公开面）；`report/redlines.py:13` 停止 import `pokemon_agent.config`（口径改读 header 快照）。
- 现有测试随文件搬家，断言不变。

**验收**：全量 pytest 绿（只换目录不动行为）；`python -m evals e2e check` 数据集校验过；`grep -rn "pokemon_agent" evals/screen_reading evals/**/redlines*` 零私有名/零 config 命中。

## R2b Scorer 收敛（V3）

- `core/scorer.py`：以 inspect `Score` 为唯一判定协议。`checks/@rule` 18 条包一层适配（证据 uuid 进 Score metadata）；红线 R1–R3 独立 scorer；`rubric/forms.py`、`report/redlines.py:22`、`checks/registry.py:15` 三套旧协议删除。
- **model-graded scorer**：`scorers/model_graded.py`，CLI 旗标注入（默认关，D6），结果分列不混机械成功率。
- **judge 一致性**改挂 e2e task 附加 scorer（取舍 B）；`process/judge_agreement.py` 的逻辑并入，独立文件删。
- `evaluate.py` 判定主输入换 `run_result.json`（RunResult）；trace 降为可选交叉核对——只在 scorer 需要证据 uuid 时经 `parse.py` 读。
- 测试：scorer 适配正反例各一（正例取 0827 真实误判）；judge 四格随迁。

**验收**：全量 pytest 绿；用 R1 的一条 `run_result.json` 手跑单样本判定，结果与改造前一致（对照旧 results.jsonl）。

## R3 eval_set 化（V2）

- `core/evalset.py`：eval_set 接管 batch.py 的循环（epochs / retry / resume / log_dir）；`runner/batch.py` 降为薄入口或删。
- **solver**（`core/solver.py`）：拼 run-one 命令 → subprocess（timeout 沿用）→ 读 `run_result.json` + scorer 结论 → inspect 输出；metadata 带 `run_id` / `sample_id` / `dataset_version` / epoch 序号。
- **run_id 后缀**：epochs>1 时 `eval-<sample_id>#e<N>`，k=1 保持 `eval-<sample_id>`。
- `cli.py`：`python -m evals evaluate --epochs N --resume …`；diff 口径校验保留在 `core/evallog.py`。
- **真机验收交你本机**：2 样本 × epochs=2 跑通；中途 Ctrl-C 后 `--resume` 只补未完成的；`inspect view` 看到同样本两个 epoch 的记录。

**验收**：上述真机三项 + 全量 pytest 绿。

## R4 manifest 扩展（V9）

- EvalLog header = 现 ReportHeader（batch.py:75-92 全套字段搬入 bridge）+ **依赖版本**（inspect-ai / pyboy / pydantic / uv.lock 摘要）+ **生成参数**（epochs / speed / knowledge / timeout / rule_ids）。
- diff 校验扩字段：新增项任一不同 → 拒绝并列差异（测试一条）。

**验收**：diff 拒绝测试过；两份口径一致的报告可比（真机小批）。

## R5 Metric 化 + 收尾（V7）

- `core/metric.py`：成功率 / pass@k / pass^k（inspect 内置 metric 优先，不满足口径再自写）；epochs=1 时 pass@k / pass^k 列 `n/a`。
- **退役**：`report/markdown.py` 删（Inspect View 接管人读层）；results.jsonl 由 EvalLog 取代；`runner/batch.py` 若 R3 未删则此处清。
- **活文档**：重写 `docs/spec/evals/SPEC.md`（照新代码）；DATAFLOW.md 相应段同步；`docs/eval/spec.md` 头部加"已被 spec2 取代"注记。
- **验收 = spec2 §十四条款逐条过**：一条命令跑完；View 总览/钻取/metadata 带 run_id；run_id 复制到 Langfuse 定位树；resume 可用；diff 拒口径不一致。

---

## 四、待你确认

| # | 问题 | 建议 |
|---|---|---|
| D5 | 预打包产物（`data/v1/checkpoints/`，20 份 run_begin 存档）进不进 git | 进——数据集冻结可复现是 E3 原则的物理载体；若单份 >10MB 再议 LFS |
| D6 | model-graded scorer 默认开还是关 | 默认关：机械判定第一真源，旗标显式开（V3 的"注入"语义） |
| D7 | report.md / results.jsonl 的退役时点 | R5 一次删净，不留过渡共存——Inspect View + EvalLog 在 R3 起就可用，拖着只会双份漂移 |

另：R0 若发现 inspect-ai API 与 spec2 假设有实质偏差（尤其 Solver 签名与 eval_set 的 resume 语义），先回 spec2 改再继续，不带偏搬迁。
