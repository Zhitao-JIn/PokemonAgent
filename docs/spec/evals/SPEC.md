# evals —— 模块规格

> 最后更新：2026-09-26 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 仓库根级包，**不在 `pokemon_agent/` 内**：它读被测系统的产物，不是被 harness 依赖的一层
> 设计来历：`docs/eval/{intent,spec,plan,p0-findings}.md`、CHANGELOG 255–260

## 〇、一项测评一个子包（0926）

不同类的测评不混放：各自的数据集、判定、报表、产物目录都在自己名下，命令行 `python -m evals <测评> <命令>`
（顶层 `cli.py` 只做分派），产物落 `eval_results/<测评>/`。

| 子包 | 测什么 | 命令 |
|---|---|---|
| `e2e/` | 端到端：样本从 run 入口跑完，出结果层 / 红线 / 路径层 / 过程层 / 效率层报告（本文第一～七节） | `python -m evals e2e …` |
| `screen_reading/` | task 层无视觉读屏：解码字段 + 整屏原样喂给文本模型，看它读不读得懂（第八节） | `python -m evals screen …` |

从 e2e 账本上顺带算的过程指标（judge 一致性、感知一致率）读的是 e2e 的产物，留在 `e2e/process/`；
独立取样、独立判定的过程集各自开子包。

## 一、职责与边界（e2e）

- **只做一件事**：把一批冻结的样本在真实链路上跑完，从盘上的账算出结果层 / 红线 / 路径层（rubric）/
  过程层 / 效率层，出一份口径可比的报告，并登记 bad case。
- **不改被测系统的行为**：样本从 run 入口进（`RunHarness.run(checkpoint_only=True)` 打包起点 →
  `restore_run` 开分支跑），停止条件用 `config` 缺省；测评读的 `sense_frame.ram` 只进账、不进 agent 输入。
- **判定只读盘**：`report` 全部由 `eval_results/<报告>/` 下的产物算出，删了能重算；不在批跑时判。
- **真值只认游戏变量与屏幕解码**：机械判据不读视觉模型抄的文字（`text_source=vlm` 的帧不作证据）。

## 二、目录结构

```
evals/
├── __main__.py / cli.py    python -m evals <e2e|screen> …（只做分派）
├── e2e/
│   ├── cli.py              python -m evals e2e：dataset check / run / report / diff（run-one 供子进程）
├── schemas/                sample.py（EvalSample / SampleStart / Rubric / RedLine）、verdict.py（SampleResult 等）、
│                           report.py（ReportHeader / BadCase / COMPARABLE_FIELDS）
├── dataset/                loader.py（load_samples / load_rubric / check / samples_digest）
│   └── v1/                 samples.jsonl（20 条）、states/*.state、rubric.json、coverage.md
├── checks/                 stream.py（RunStream / Frame）、registry.py（RULES / @rule / judge）、utils.py、
│   └── rules/              movement / dialog / shop / battle / catch / center：18 条机械判据
├── rubric/                 redundant.py（代码项，只给原始量）、forms.py（人工表单与 rubric_scores.jsonl）
├── process/                judge_agreement.py（judge 四格、task 收尾分布）、sense_agreement.py（解码 vs 视觉）
├── report/                 redlines / efficiency / evaluate（一条样本）/ assemble（build_report）/ markdown / diff
├── cases/                  bad_cases.py（collect / append_new，只追加、去重）
└── runner/                 batch.py（run_batch，一条样本一个子进程）、one.py（run_one）
```

## 三、数据集

- 一条样本 = `EvalSample`：`start`（`run_begin` + `.state` 路径与 sha256；`recovered_episode` 预留）、
  `goal` / `success_criteria` / `max_steps`、`behavior`（可行做法）、`check_id`（机械判据，可空）、
  `rubric` / `red_lines`（引用 `rubric.json` 的 id）、`k_metric`（`pass_at_k` / `pass_hat_k`）、`split`。
- **冻结的是源、不是存档**：存档清单带 `state_schema_hash`，`RunState` 一改旧存档就拒载，所以每次批跑现打包。
- `python -m evals e2e dataset check` 核：文件存在、哈希一致、rubric / 红线 / 判据 id 都有定义。改样本 = 出新版本目录。

## 四、判定

| 层 | 谁算 | 规则 |
|---|---|---|
| 结果层 | `checks.judge` | 按 `check_id` 调判据，给 `pass` / `fail` / `unjudgeable` + 证据帧 uuid；不可判的不进分母 |
| 红线 | `report/redlines.py` | R1 出错（`run_error` / `episode_error` / run 以 error 收尾；停摆不算）；R2 刹车失灵（连续失败达停摆上限后仍派 task / 仍开局）；R3 谎报成功（run 以 `goal_done` 收尾而判据 fail）。命中即判负 |
| 路径层 | `rubric/` | 0–2 档；`redundant_path` 给按键 / 回到旧格 / 无效按键原始量（阈值待标定）；`decompose_quality` / `strategy_switch` 人工打分 |
| 过程层 | `process/` | judge 与判据的 TP/FP/FN/TN（run、task 两层）；task 收尾分布；解码 vs 视觉逐帧一致率 |
| 效率层 | `report/efficiency.py` | 按链路的调用数与 token、按键、调用失败 / 重试耗尽、局数 / task 数、墙钟 |

## 五、批跑与产物

`python -m evals e2e run [--samples a,b] [--model M] [--no-knowledge] [--timeout S]`：

1. 写口径头 `header.json`（git 提交与脏否、五条链路型号、`config` 全部大写旋钮、数据集 / rubric 版本、样本哈希、知识库哈希）。
2. 每条样本起子进程 `run-one`：在 `runs/<sample_id>/` 下建独立 `trace/` / `memory/` / `checkpoints/`，
   打包起点 → `restore_run` → 写 `run.json`（`run_id` / `invalid` / `error`）。超时即杀，记"没有批跑记录"。
3. `build_report`：`results.jsonl`、`report.md`、`rubric_forms.md`，追加 `bad_cases.jsonl`。

`python -m evals e2e report <目录>` 按盘上产物重算（读回人工填的 `rubric_scores.jsonl`）；
`python -m evals e2e diff A B` 口径（`COMPARABLE_FIELDS`）不同即拒绝对比，否则列翻转样本。
产物在 `eval_results/e2e/`，不进 git。

## 六、测试

`tests/test_evals_checks.py`：每条判据一正一反（`set(CASES) == set(RULES)` 守住"新判据必须带样例"），
外加"视觉文字不算"一条。读侧解析的回环在 `tests/test_trace_parse.py`。

## 七、当前状态与已知缺口

- 离线已通：数据集核对、判据样例、报告在假目录上出齐产物。**真账本全链路待真机批跑（plan E9）**。
- `battle_pokemon_switch` 无机械判据；`redundant_path` 档位阈值、样本难度待第一批数据标定。
- 判据只读 `ram.decoded`（每帧都记）；解码切不出的界面（队伍列表、数量框）上相关判据只能靠游戏变量。
- 只有 `k=1`；pass@k / pass^k 的多次重复与分层门禁、CI 接入在后续版本。

## 八、读屏测评（`screen_reading/`）

**问的是**：task 层不调视觉，只拿解码字段 + 整屏原样（`Facts.screen`）；文本模型据此能不能说对屏幕上的
叠加层、对话、选项、光标、数量。

- **数据集 v1**（`screen_reading/dataset/v1/samples.jsonl`，451 帧，一帧一条：tile 缓冲 + 截图 + 人工标注）：
  - `observation_check` 406 帧：当年只存了截图，缓冲由 `glyphs.py` 逐块还原（字形库从 VRAM 解、按明暗首次
    出现顺序归一以抗调色板变化、网格起点 0–7 像素逐个试以抗整屏抖动）；标注沿用 `claude_label`。
  - `probe_0926` 45 帧：存档按键实采，缓冲是真的；标注见 `probe_0926.json`（与 `Claude outputs/decode_review.html` 同一批）。
  - 还原在 45 帧真缓冲上核过：44 帧解码字段逐项一致，唯一差异是对话逐字打出时截图比缓冲慢一帧。
  - `python -m evals screen build` 重造（要 ROM）；产物冻结进仓库，跑测评不再要 ROM。
- **观测**（`observe.py`）：与 `PyBoyWorld._ram_observe` 同一套 `read_screen_text` / `_overlay_of` / `_layout_field`，
  按 `decide_action.py` 的 `- 键: 值` 写法渲染（地形字段不在这里测）。
- **两种读法并排打分**（`grade.py`，精确匹配、只规整空白）：**解码直出**（不调模型，字段原样）与**模型读后**
  （`prompt.md` 问一次，JSON 回答）。`quantity` 只在标注有值的帧上打分。
- **报表**：按字段 / 来源 / 界面桶（由解码结果分：纯对话、选单、选单(解码切不全)、数量框、无叠加……）/ 0926 类别，
  再列出模型读错的帧。
- **首个基线**（0926，解码直出、未调模型）：451 帧全对 418；纯对话 169/169、选单 63/65；
  选单(解码切不全) 0/6、数量框 1/12——这两桶就是要看模型读整屏原样能补回多少。
- **已知的标注口径差异**：`observation_check` 的标注是按"看图"标的，空对话框也标 `dialog`、图鉴条目的说明文字
  算对话；这类帧解码直出必然判错，模型读后也可能判错——看报表"读错的帧"时区分口径问题与真读错。

