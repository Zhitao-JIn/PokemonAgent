# spec2 —— evals 骨架重映射（inspect-ai 真依赖轻用）

> 流程位置：intent.md → **spec2.md** → plan → PR → production（取代 spec.md 的角色；spec.md 保留作 v1 记录，其〇节偏差与 E1–E8 落码状态仍是有效事实）
> 状态：**已定稿（09-28）**：fork #1 裁决「**inspect view 看结果，langfuse 看过程**」（09-28 08:0x 用户拍板）→ 真依赖轻用；下一步写 plan
> 依据：`docs/eval/intent.md` §十一 V1–V12（09-28 拍板）+ §十一对标节（21 维评级）+ CHANGELOG 315/316
> 范围：evals 包骨架、与 harness 的接口（V8）、观测三层分工。**不改** agent 决策侧、trace 格式、Langfuse 树形约定（0927 定稿）

---

## 〇、fork 裁决与它消灭了什么

09-28 用户拍板：**inspect view 看结果，langfuse 看过程**。这句话定了三件事：

1. **真依赖**：pip 装 `inspect-ai`（版本钉进 pyproject），Task / Solver / Scorer / Metric / eval_set / EvalLog 全部用真协议——`evals/core/` 六文件从"自研实现"降为**薄适配**（re-export + 项目侧收敛），不再自造协议。
2. **过程回放不进 Inspect View**：35 种 trace kind **不做** inspect 事件 schema 映射——机械事实（按键、模拟器帧、记忆检索）在 inspect 里只能以 JSON metadata 形态展示，不值得适配。过程层归 Langfuse 已有设施（三层树 0927 定稿、rehearsal 已过）。
3. **bridge 层瘦身**：唯一需要的"翻译"是 sample ↔ run_id ↔ Langfuse 的**对应关系**（§二），不是数据搬运。

**消灭的问题**：原 V8 讨论里"eval 读返回值还是读 trace"之外的第三个隐含选项——"把 trace 富渲染进自家 viewer"——从范围里划掉，那是周级自研工作量，已被两层分工覆盖。

## 一、观测三层分工

| 层 | 工具 | 看什么 | 状态 |
|---|---|---|---|
| **结果层** | Inspect View | 指标总览、sample 钻取（scorer 结论 + metadata）、log history 对比、live view（`inspect view` 起 7575 端口，跑批进行中可看） | 新增 |
| **过程层** | Langfuse | 逐键 trace 树（branch scope → run_start → episode_start → task_start → step 平铺） | 已有 |
| **人在环** | WebReviewer | 过程审查、WebSocket 推送 | 已有，**不动** |

**对应机制（本 spec 的关键接线）**：

- `run_id = eval-<sample_id>`（`evals/e2e/runner/one.py:52` 现状升为契约，V1）；
- Langfuse 侧 trace_id 由 `create_trace_id(seed=run_id)` 生成（`pokemon_agent/trace/langfuse_trace.py`）——**run_id 就是过程层的主键**；
- solver 把 `run_id` 写进 sample 的 inspect metadata（顺带 `sample_id`、`dataset_version`、`epoch` 序号）。Inspect View 里看到可疑 sample → 复制 run_id → Langfuse 直接定位该局 trace 树。epochs>1 时 run_id 加 epoch 后缀（`eval-<sample_id>#e<N>`），k=1 保持原样不破已有报告。

**退役项**：`report/markdown.py` 的人读报表渲染（Inspect View 接管人可读层）；`results.jsonl` 由 EvalLog 取代（机器可读层不丢）。**保留项**：diff 的口径一致性校验（Inspect View 的 log history 只做展示，不校验口径可不可比——这份逻辑自有价值）。

## 二、目标骨架

```
evals/
├── __init__.py / __main__.py / cli.py      入口：python -m evals evaluate / view / diff
├── core/                  inspect-ai 真协议的薄适配
│   ├── task.py            @task 装配 dataset+solver+scorers+metrics（每类测评一个）
│   ├── solver.py          被测对象槽位：包 run-one 子进程（§四取舍 A）
│   ├── scorer.py          (state, target) → Score 协议 + 三套旧协议的收敛注册表
│   ├── metric.py          成功率 / pass@k / pass^k（inspect metric 协议，V7）
│   ├── evalset.py         eval_set 编排：epochs(V2) / retry / resume / log_dir
│   └── evallog.py         .eval 日志读侧 + diff 口径校验（V9 manifest 的载体）
├── bridge.py              项目 ↔ inspect 翻译：EvalSample→Dataset、模型档/根目录→solver 参数、
│                          RunResult→sample metadata（含 run_id）、ReportHeader→EvalLog header
├── tasks/                 每类测评一个 @task（intent 对标表落点）
│   ├── e2e.py             20 样本端到端（judge 一致性作附加 scorer 挂它上，§六）
│   ├── macros.py / screen_reading.py / takeover_views.py
│   └── judge_process.py   过程集扩充（拆解质量/卡住换策略）时启用，v1 留位
├── scorers/               机械 @rule 18 条 + 红线 R1–R3 + model-graded scorer（V3）
├── data/                  数据集：v1 冻结（states/ + samples.jsonl + coverage.md + 预打包存档）
└── data/loader.py         读 + 校验冻结（哈希对不上即拒）
```

**迁移映射**（旧 9 子目录 → 新骨架，搬完旧目录删除）：

| 旧 | 新 | 动作 |
|---|---|---|
| `e2e/schemas/` | `bridge.py` + `core/evallog.py` | EvalSample 保留；ReportHeader 并入 EvalLog header；CheckVerdict→Score |
| `e2e/dataset/` | `data/` | 原样搬 + 预打包（§五） |
| `e2e/runner/` | `core/solver.py` + `core/evalset.py` | run-one 子进程保留、batch 的循环交给 eval_set |
| `e2e/checks/` + `e2e/report/redlines.py` | `scorers/` | 协议收敛到 Score（§六） |
| `e2e/report/` | `core/evallog.py`（diff 口径校验）+ 退役（markdown 渲染） | efficiency 的字段进 RunResult（§五） |
| `e2e/rubric/` + `e2e/process/` | `tasks/judge_process.py`（v1 留位）+ e2e 附加 scorer | 见 §六 |
| `macros/` `screen_reading/` `takeover_views/` | `tasks/` 各一 + 骨架复制收敛进 core | 21 维评级⑤修正 |

**边界纯净度修正**（21 维评级⑤，随迁移一并做）：`screen_reading/observe.py:10-12` 停止 import 被测私有名（契约上移到 `world` 公开面）；`report/redlines.py:13` 停止 import `pokemon_agent.config`（口径以 EvalLog header 快照为准，不读 live config）。

## 三、数据流（一条样本的生命周期）

```
data/v1（冻结样本 .state + sha256 + goal）
  → 预打包 run_begin 存档（一次性，产物冻结进 data/v1/，V1 拍板）
  → solver：subprocess 跑 run-one（build_real + restore_run，独立 trace/memory/checkpoint 根）
      → run 跑完，子进程把 RunResult 落盘 run_result.json
  → bridge：RunResult + scorer 结论 → sample metadata（run_id 在内）
  → scorer：机械 @rule（第一真相源）+ model-graded（V3，evaluate 启动时注入，结果分列）
  → metric：成功率 / pass@k / pass^k
  → EvalLog（.eval）落 log_dir；header = manifest（V9）
  → Inspect View 看结果 ←run_id→ Langfuse 看过程
```

- **判定的真相源不变**：机械判定第一、judge 是被测对象、model-graded 分列不混入机械成功率（intent §六-1，V3）。
- **V8 的兑现**：scorer 主要输入是 RunResult（结构化返回值）；trace 降为可选交叉核对（证据 uuid 需要时经 `tools/trace/parse.py` 读，读侧解析层 259 已落）。
- **样本无效 ≠ 判负**：起点哈希不对 / 存档拒载记 `invalid`，不进分母（spec.md §七原则平移）。

## 四、两个设计取舍

**取舍 A：solver 保留子进程隔离，不进 inspect 的进程内循环。**
inspect 的 eval_set 在一个进程里顺序跑样本；但本项目被测对象是 PyBoy 进程 + 模拟器，batch.py 现状的"每样本一个子进程，卡死/崩溃不连累别的（超时即杀）"是真实需求。solver 因此变薄：拼 run-one 命令行 → `subprocess.run(timeout)` → 读 `run_result.json` → 组装 inspect 输出。epochs/resume 由 eval_set 在外层管，与子进程隔离不冲突。代价：inspect 的 solver 内部并发能力用不上（本项目本来就不并发，一次只跑一个）。

**取舍 B：judge 一致性先作 e2e task 的附加 scorer，不拆独立 task。**
intent 对标表写"每类测评一个 task"（含 judge 过程集）；但 v1 的 judge 一致性（TP/FP/FN/TN）与机械判定消费**同一个 run 的产物**——拆成独立 task 意味着 solver no-op 重扫一遍产物，纯绕路。v1 挂在 e2e task 上当第二个 scorer；将来过程集扩充（拆解质量/卡住换策略，需要独立样本与打分流程）时再拆 `judge_process.py`。这是对标表的一处有意偏离。

## 五、RunResult（V8，harness 侧改动，单独提交）

现状：`harness/run/harness.py:79` 返回裸四元组 `tuple[list[EpisodeOutput], int, int, float]`，evals 零消费（report 全靠读 trace，`report/evaluate.py:26-36`）。改为结构化 Pydantic 模型（铁律 5）：

| 字段 | 内容 |
|---|---|
| `run_id` / `sample_id` | 对应关系主键（sample_id 由 eval 传入，harness 原样带回） |
| `outcomes` | 逐局：`episode_id` / `task_id` / `termination` / `success` / `judge_reason` |
| `steps` | 步数、按键数（run / episode 两级） |
| `usage` | 分链路 token 与调用次数、`call_failed` 次数 |
| `wallclock` | 墙钟起止 |
| `episode_bounds` | 逐局边界（起止事件 uuid，供可选交叉核对定位） |

子进程把 RunResult 落盘 `run_result.json`（与现有 `run.json` 同目录，bridge 读它组 metadata）。

## 六、Scorer 收敛（V3 + 21 维评级①）

现状三套并行协议：`checks/registry.py:15`（CheckVerdict）/ `report/redlines.py:22` / `rubric/forms.py`。收敛到 `core/scorer.py` 一个协议（inspect 的 `(state, target) → Score`）：

- **机械 @rule 18 条**：纯函数保留，注册表防重保留，外层包一层 Score 适配；证据 uuid 进 Score 的 metadata（最小可归因不变）；
- **红线 R1–R3**：独立 scorer（命中即 0 分 + 理由），多 scorer 并列是 inspect 的原生形状；
- **model-graded scorer**（V3）：evaluate 启动时经 CLI 旗标注入，结果与机械判定**分列**，不混进机械成功率；
- **judge 一致性**：e2e task 附加 scorer（取舍 B），四格结论进 Score metadata。

## 七、manifest（V9）

EvalLog 的 header 承载口径，在现有 ReportHeader（`batch.py:75-92`：git commit / dirty、五链路模型、config 旋钮快照、数据集样本哈希、rubric 版本、知识库哈希）上扩：**依赖版本**（inspect-ai、pyboy、pydantic…）+ **生成参数**（epochs / speed / knowledge / timeout / rule_ids）。diff 校验规则不变：除 git commit 外任一项不同 → 拒绝对比并列差异。

## 八、实现顺序（CHANGELOG 315 影响面五步，维持）

① RunResult（V8）→ ② evals 骨架重映射 + Scorer 收敛（V5/V3，含边界修正）→ ③ eval_set 化：epochs/retry/resume（V2）→ ④ manifest 扩展（V9）→ ⑤ Metric 化 + pass@k/pass^k（V7）。每步一条 CHANGELOG 编号条目、独立 commit。

## 九、不做什么（范围墙）

- trace 不映射进 inspect 事件 schema；逐键回放只有 Langfuse 一个入口；
- 不动 WebReviewer、不改 Langfuse 树形约定；
- 不做显著性检验（V6 暂缓）、不做归因（V11 只留测评记录）、不做 train/val/test 三分（316，单一数据集 + 版本冻结）;
- v1 不拆 judge 独立 task（取舍 B）；不做 solver 内并发；
- 测评期间不调参刷分（intent §十）。

## 十、成功样子（spec2 层验收）

1. `python -m evals evaluate --dataset v1` 跑完，`inspect view` 打开 log_dir：总览有成功率 / pass@k / pass^k，点进任一 sample 能看到 scorer 结论与 metadata 里的 run_id；
2. 拿那个 run_id 去 Langfuse 能直接定位该局三层 trace 树——**结果与过程之间只隔一次复制粘贴**；
3. epochs=3 的跑批中途中断后可 resume；两份口径一致的报告可 diff，不一致的被拒；
4. `evals/` 内不再有三套判定协议、不再 import 被测私有名与 live config。
