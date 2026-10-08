# spec —— 测评 task 改名 + 数据集重整 + judge 扩容 + choose 节点测评

> 流程位置：tasks-intent.md → **tasks-spec.md** → tasks-plan.md → PR → production
> 依据：`docs/eval/tasks-intent.md`；现状以 2026-10-07 仓库为准（CHANGELOG 392，对外六个 task）
> 顺序：S1 改名与目录按槽位归位 → S2 数据集重整 → **S1b 过程 trace 进 Inspect transcript** → S3 judge 扩容 → S4 choose。（S1、S2 已落地：406、407）每步一条（或一组）CHANGELOG 编号条目，独立 commit。

---

## 〇、暂定项（按推荐写入，可推翻）

intent 第六节里没拍板的项，本 spec 先按推荐方案写；推翻哪一项只影响对应小节。已拍板的也列在这里，便于对照。

| 编号 | 暂定方案 | 影响小节 |
|---|---|---|
| D1（已定） | 数据**生产**工具进对应数据集包的 `build/` 子目录（读与造在一处；不叫 `tools/`，避免和生产代码的"tool 层"同名） | §二 |
| 槽位（已定） | 所有 solver 进 `evals/solvers/`，所有 scorer 与 metric 进 `evals/scorers/`，按 task 名分文件（文件多的开同名子包）；task 目录只留 `task.py`；`evals/core/` 解散 | §1.4 |
| J1 | choose 可接受集合：**按键**在存档上逐个重放、按"推进谓词"自动预标，人工审；**脚本**人工标 | §4.3 |
| J2 | 现场采集：evals 侧录制器（装饰 `ChoosePort` / `JudgePort`），只在 `run-one --capture` 时装上，不改生产代码 | §五 |
| J3 | 首版规模：choose v1 ≈ 60 条（6 个场合 × 10，三个难点标签各 ≥ 10）；judge v2 ≈ 80 条（正负各半，每类难负例 ≥ 8） | §三、§四 |

---

## 一、S1 改名

### 1.1 映射

| 现 task | 新 task | task 目录（只含 `task.py`） | `@task` 函数名 |
|---|---|---|---|
| decode | decode | `evals/tasks/decode/`（不动） | `decode` |
| vision_perceive | episode_vision_read | `evals/tasks/episode_vision_read/` | `episode_vision_read` |
| world_actions | world_script_execute | `evals/tasks/world_script_execute/` | `world_script_execute` |
| memory | memory_store_recall | `evals/tasks/memory_store_recall/` | `memory_store_recall` |
| judge | brain_goal_judge | `evals/tasks/brain_goal_judge/` | `brain_goal_judge` |
| e2e | agent_goal_run | `evals/tasks/agent_goal_run/`（单文件 `e2e.py` 收成包；`result_grade.py` 是 scorer，按 §1.4 进 `evals/scorers/`） | `agent_goal_run` |
| （S4 新增） | brain_choose_action | `evals/tasks/brain_choose_action/` | `brain_choose_action` |

### 1.2 连带改动

- `evals/tasks/registry.py`：键与路径按上表；`python -m evals run <新名>`。
- `evals/e2e/`（`runner/one.py`、`cli.py`）是 run-one 子进程的本体，属于 agent_goal_run 的 solver，并入 `evals/solvers/agent_goal_run/`；子进程入口 `python -m evals e2e run-one` 改为 `python -m evals agent_goal_run run-one`（`evals/cli.py` 同步）。`run_id = eval-<sample_id>[#e<n>]` 不变（Langfuse 对应关系不断）。
- 测试：`tests/test_evals_tasks.py`（公开 task 集合、各 task import 路径）、`test_evals_scripts.py`、`test_evals_perceive.py`、`test_evals_checks.py`、`test_evals_scoring.py` 的 import 路径。
- 文档：`docs/spec/evals/SPEC.md` 总表与命令；AGENTS.md / CLAUDE.md 的 task 清单（两份逐字同步）。
- **不改**：被测系统代码；各 task 的 solver / scorer 的逻辑与评分口径（§1.4 只搬位置）。

### 1.3 验收

`python -m evals list` 恰好列出六个新名；`tests/test_evals_tasks.py` 断言集合与"`@task` 函数名 = 注册名"；`evals/tasks/*/` 下除 `task.py`（与 `__init__.py`）外没有别的文件；`evals/core/` 不存在；全量 pytest 与 ruff 不比改名前多出失败。

### 1.4 目录按 inspect 槽位归位，`evals/core/` 解散

**规则**：

```
evals/
├── tasks/<task>/task.py   只做装配：dataset.load() + solver + scorer
├── solvers/               所有 solver：<task>.py（或同名子包）+ 跨 task 共用的零件
├── scorers/               所有 scorer 与 metric：<task>.py（或同名子包）+ 跨 task 共用的（现有机械判据 @rule、红线、RunStream 不动）
└── dataset/<名>/          §二
```

- metric 不单设目录：它挂在 scorer 上（`@scorer(metrics=[...])`），是把一批 Score 汇总成一个数的那部分，和 scorer 放一起。
- solver → scorer 的交接记录（`StoreModel` 与它装的 `*Run`）由 solver 产出，放 `solvers/<task>`；判定结论类型（`*Verdict`）放 `scorers/<task>`。scorer 可以 import solver 的记录类型，反向不许。
- 样本契约（`ScriptCase`、`JudgeCase`、`MemoryDataset`…）属于数据集，S2 进 `evals/dataset/<名>/schemas.py`；S1 期间先随 task 留在 solvers 侧，S2 再搬。

**搬迁表**：

| 现位置 | 新位置 |
|---|---|
| `evals/core/judged.py` | `evals/scorers/judged.py` |
| `evals/core/score.py` / `scorer.py` / `metric.py`（引入 inspect 前自造的 Score / Scorer / Metric，现在只有 agent_goal_run 用） | `evals/scorers/agent_goal_run/` |
| `evals/core/solver.py`（run-one 子进程 solver） | `evals/solvers/agent_goal_run/solver.py` |
| `evals/core/world_case.py`（起模拟器、按开跑前的键、读帧） | `evals/solvers/world_case.py`（world_script_execute 的 solver 与 frames 的采集工具共用） |
| `evals/core/frames.py`、`evals/core/snapshot.py` | S2 进 `evals/dataset/frames/`（S1 期间先放 `evals/solvers/frames.py`、`evals/solvers/snapshot.py`） |
| `evals/core/task.py`、`evals/core/evalset.py`（只 re-export inspect） | 删除 |
| `decode/{solver,schemas}.py` / `decode/scorer.py` | `solvers/decode.py` / `scorers/decode.py` |
| `vision_perceive/{solver,schemas}.py` / `scorer.py` | `solvers/episode_vision_read.py` / `scorers/episode_vision_read.py` |
| `memory/{solver,schemas}.py` / `task.py` 里的 `storage_scorer`、`retrieval_scorer`、`retrieval_metrics` | `solvers/memory_store_recall.py` / `scorers/memory_store_recall.py` |
| `judge/task.py` 里的 `judge_solver` / `judge_scorer`、`confusion` 与 `judge/metrics.py` | `solvers/brain_goal_judge.py` / `scorers/brain_goal_judge.py` |
| `world_actions/{solver,schemas}.py` / `scorer.py`、`takeover_samples.py::judge_takeover`、`takeover_contract.py` 里的 12 个核对函数 | `solvers/world_script_execute.py` / `scorers/world_script_execute/`（子包：`scorer.py`、`takeover_checks.py`） |
| `e2e.py` 里的 `e2e_scorer`、`result_grade.py` | `scorers/agent_goal_run/` |
| `evals/schema/verdict.py`（`CheckVerdict`，机械判据产出） | `evals/scorers/verdict.py` |


---

## 一b、S1b agent_goal_run 的过程 trace 进 Inspect transcript

> **推翻 spec2 §〇-2"过程不进 Inspect View"**（用户 2026-10-08 定）：Inspect View 既看结果也看过程；Langfuse 保留，不再是看过程的唯一入口。
> 可行性已用原型验证：`eval_results/trace_view_demo/`（真实 run `knowledge_door_transition` 的 168 条账回放成 `.eval`，`inspect view --log-dir eval_results/trace_view_demo` 可看；原型脚本 `prototype_trace_view_task.py` 在同目录，只作参照，不进代码）。

### 1b.1 做什么

agent_goal_run 的 solver 在 run-one 子进程跑完后，把这条样本的项目 trace 读出来，**按真实发生顺序、带原始时间戳**逐条追加进该样本的 Inspect transcript。View 的 Transcript 标签页里按 run → episode → task 嵌套显示，模型调用、动作、记忆读写、其余账各用最合适的 inspect 事件类型。

其余五个 task 没有项目 trace，不涉及。

### 1b.2 读账

- 用现有 `evals/scorers/stream.py::RunStream.load(trace_root, run_id, branch, backend)`（local 与 langfuse 两种后端都支持，和 scorer 同一个读法），得到已按 `(ts, uuid)` 排好、只含本次恢复执行线的 `ParsedEvent` 列表。
- 不直接读 json 文件（原型那样只是为了验证）。

### 1b.3 事件映射

| 账 | inspect 事件 | 字段 |
|---|---|---|
| `run_start` / `episode_start` / `task_start` | `SpanBeginEvent` + 一条 `InfoEvent`（该账内容） | `id` = 账 uuid；`type` = run / episode / task；`name` = `<层> <id>`；`parent_id` = 外层 span |
| `run_end` / `episode_end` / `task_end`，以及 `run_error` / `episode_error` / `task_error` | 一条 `InfoEvent`（该账内容）+ `SpanEndEvent` | 关掉对应层（错误账同样收口，未配对的 span 在回放末尾统一关闭） |
| `parse.MODEL_CALL_KINDS` 里的全部调用账（`sense_call`、`choose_call`、`plan_call`、`decompose_call`、`judge_call`、`verify_call`、`summarize_episode_call`、`summarize_task_call` …） | `ModelEvent` | `model` = 该链路的型号名（取自 task 装配时的 `models`，取不到写链路名）；`role` = 账名；`input` = 一条 `ChatMessageUser`：`ContentText(prompt)` + 每张图一个 `ContentImage(data URI)`；`output` = `ModelOutput.from_content(model, raw)`，`usage` 填 `input_tokens` / `output_tokens` / `input_tokens_cache_read`(=cached) / `reasoning_tokens`；`ok=false` 时填 `error`；`call` = `ModelCall(request=<该账完整内容>, response={"raw": raw})`；`timestamp` = `started_at`，`completed` = `ended_at`，`working_time` = 两者差 |
| `act_call`（以及历史账名 `press_key` / `run_macro`）、`get_action_space`、全部 `read_*` / `write_*` 记忆账 | `ToolEvent` | `id` = 账 uuid；`function` = 账名；`arguments` = `{"meta": …}`；`result` = 该账完整内容的 JSON 文本；`timestamp` / `completed` / `working_time` 同上 |
| 其余所有账（`*_verdict`、`sense_frame`、`settle_*`、`checkpoint_*`、`review_*`、`call_failed`、`call_exhausted`、`check_stall`、`advance_step` …） | `InfoEvent` | `source` = 账名；`data` = `{"type", "meta", "content"}` 完整内容 |

**所有事件共同的规则**：

- `timestamp` 取账的 `started_at`（不用"现在"）；按 `RunStream` 的顺序追加，View 显示的就是真实顺序。
- `uuid` 用账的 uuid，`metadata` 写 `{"kind", "type", "trace_uuid"}`，能和 Langfuse / 盘上账本一一对应。
- **字段全保留**：每条账的 `meta` 与 `content` 原样进事件（`ModelEvent` 进 `call.request`）。
- **截图**：账里是 base64 data URI，原样进事件；inspect 写日志时自动抽成附件、按内容去重（原型 168 条账 84 KB）。

### 1b.4 solver / scorer 交接改走 store

- solver 跑完后读 `run.json` 与 `run_result.json`，写 `AgentRunRecord(StoreModel)`：`run_id`、`branch`、`invalid`、`error`、`work_dir`、`run_result`（原 `state.output.completion` 里的那份，仍保留在 completion 里供 View 展示）。
- `scorers/agent_goal_run/task_scorer.py` 与 `result_grade.py` 改从 `store_as(AgentRunRecord)` 取 `run_id` / `branch` / `invalid` / `work_dir`，不再自己拼工作目录、读 `run.json`；读账仍用 `RunStream.load`（scorer 需要类型化账本，不从 transcript 反读）。
- `invalid` 或超时的样本不回放（没有可回放的账），transcript 里写一条 `InfoEvent` 说明原因。

### 1b.5 开关与依赖风险

- task 参数 `-T transcript=true|false`，缺省 `true`。关掉时只写 store，行为与现在一致。
- 追加事件要用 `transcript()._event(...)`（inspect 内部接口；`span()` 与 `info()` 这两个公开接口会把时间戳盖成"现在"）。inspect 版本已在 `pyproject.toml` 锁 `0.3.271`；升级 inspect 时必须跑 §1b.6 的测试。

### 1b.6 验收

1. **单元测试**（不跑游戏、不连网）：用构造的 `ParsedEvent` 列表（覆盖 span 三层、一条带图的模型调用、一条 act_call、一条记忆读、一条 verdict、一条未配对的 error）调回放函数，断言：事件类型与上表一致；时间戳等于原账 `started_at`；顺序与输入一致；span begin / end 成对且嵌套正确；图片成为 `ContentImage`；scorer 从 store 读到 `run_id` / `branch`。
2. **离线回放**：拿 `eval_results/inspect/runs/knowledge_door_transition/trace` 这份真实账本跑回放（同原型），事件数与各类型计数和原型一致（不含原型多出的主线 `checkpoint_save`，`RunStream` 只取恢复执行线）。
3. **真机**（用户本机，需模型 API）：`python -m evals run agent_goal_run --limit 1`，`inspect view` 打开，Transcript 里能看到三层嵌套、模型调用带截图、时间与 Langfuse 里同一 run 一致。

---

## 二、S2 数据集重整：`evals/dataset/<名>/`

### 2.1 包的统一形状

```
evals/dataset/<名>/
├── __init__.py      出口：只 re-export `load` 与样本类型
├── schemas.py       样本的数据契约（数据集产出它）
├── loader.py        load(version: str = DEFAULT_VERSION) -> list[<样本类型>]；核冻结；挂真值
├── build/           （D1）采集 / 构建 / 打包 / 审核工具；task 运行时不 import
└── v1/ v2/ …        冻结文件；冻结后不改，要改出新版本
```

**契约**：

- `load()` 是 task 拿数据的唯一入口；task 不拼路径、不读文件。
- `load()` 返回**类型化**样本（Pydantic），不返回 dict。
- 版本目录自包含：样本里的相对路径一律相对**本版本目录**（不再相对仓库根），存档等引用文件都在本版本目录下。
- `loader.py` 校验失败（文件缺失、哈希不符、真值重复）抛具名异常 `DatasetError`（已有，迁入 `evals/dataset/errors.py`，各包共用）。
- task 自己的运行期记录（`StoreModel`、`*Run`、`*Verdict`）留在 `evals/tasks/<task>/schemas.py`，不进数据集包。

### 2.2 各包

| 包 | 样本类型 | 冻结文件 | 读取代码来源 | build/ 来源 |
|---|---|---|---|---|
| `frames` | `ScreenSample`（+ 挂上的 `FrameTruth` 各组） | `v2/samples.jsonl`、`v2/truth.jsonl`；`sources/`（接管 8 帧与地形 2 帧的采集输入：`capture_cases.jsonl` + `states/`） | `evals/data/frames/{schemas,truth}.py`、`build.py::load_samples`、`frames.py`、`snapshot.py`（S1 后暂在 `evals/solvers/`；WRAM + ROM bank 0 的快照内存，帧读取的一部分） | `build.py`（构建部分）、`glyphs.py`、`observe.py`、`freeze.py`、`terrain.py`、`storage.py`、`coverage.py`、`deduplicate.py`、`cli.py` |
| `agent_goal_run` | `EvalSample`、`RubricItem`、`RedLine` | `v1/samples.jsonl`、`v1/states/`、`v1/archives/`、`v1/rubric.json`、`v1/coverage.md` | `evals/data/loader.py`、`evals/schema/sample.py` | `evals/data/pack.py` |
| `world_script_execute` | `ScriptCase`、`ScriptExpect`、`TakeoverCheck` | `v1/cases.jsonl`（106 条）、`v1/states/` | `evals/tasks/world_actions/{cases,regular_batch_*,takeover_*}.py` 里的用例与常量 | 一次性转换脚本 `build/convert_cases.py`（转换完成即可删，见 §2.3） |
| `memory_store_recall` | `MemoryDataset` | `v1/dataset.json` | `evals/tasks/memory/schemas.py` 的数据集部分、task 里的读文件代码 | — |
| `brain_goal_judge` | `JudgeCase` | `v1/dataset.jsonl`（现 4 条）；S3 出 `v2/` | `evals/tasks/judge/schemas.py::JudgeCase`、task 里的读文件代码 | S3 的标注工具 |

`evals/data/` 包与 `evals/schema/sample.py` 迁完后删除（`verdict.py` 已在 S1 进 `evals/scorers/`），`evals/schema/` 删除。

### 2.3 world_script_execute：用例转成数据

**常规用例**（31 条）本来就是纯数据的 `ScriptCase`，原样 `model_dump` 成 jsonl。

**接管用例**（75 条）带 Python 可调用的 `checks`，转换前先把核对改成**声明式词表**：

```python
class TakeoverCheck(BaseModel):
    kind: Literal["money", "bag", "scene", "left", "battle_start", "in_play",
                  "foe_hurt", "shop_start", "pc", "order", "box", "knows"]
    args: dict[str, str | int | bool | list[str]] = {}
```

- 12 个 `kind` 与 `takeover_contract.py` 现有的 12 个核对工厂一一对应（`_money` / `_bag` / `_scene` / `_left` / `_battle_start` / `_in_play` / `_foe_hurt` / `_shop_start` / `_pc` / `_order` / `_box` / `_knows`），参数照搬；`_UNCHANGED` 展开成四条。
- 判定函数（`kind` → `(before, after, args) -> str`）是**评分逻辑**，留在 `evals/scorers/world_script_execute/takeover_checks.py`；数据集只存声明。
- `ScriptExpect` 增加 `checks: list[TakeoverCheck] = []`、`status: str | None`、`summary: str = ""`；`takeover_samples.py` 的运行时转换删除，常规与接管走同一条 `load()` → Sample 路径，`judge_takeover` 并入统一 scorer。
- **等价性验收**：转换前后同一批用例在真模拟器上逐条判定结果相同（106/106 一致）。

**存档**：`cases.jsonl` 里的 `state` 改为相对 `v1/states/`；用到的 `experiment/experiment_states/{knowledge,macros}/*.state` 拷进来（`experiment/` 那份不动）。

### 2.4 agent_goal_run：搬迁不改版本

`samples.jsonl` 里 `start.source_state` 从 `evals/data/v1/states/x.state` 改为 `states/x.state`（相对版本目录）；`source_sha256` 不变（文件内容没变）。版本号保持 `v1`，在 CHANGELOG 记"路径重写、内容未变"。`archives/*/manifest.json` 里若含仓库相对路径同步改写，`pack.py` 的输出目录跟着改。

### 2.5 验收

- task 目录下不再有 `*.json` / `*.jsonl` / 用例常量文件；`evals/data/`、`evals/schema/` 不存在。
- 每个 task 只 import `evals.dataset.<名>` 的出口拿数据（可用 grep 核对）。
- 六个 task 各跑一遍（不调模型的三个跑全量，调模型的三个用 `--limit 1` 或 `-T` 小样本）结果与重整前一致。

---

## 三、S3 judge 扩容（`brain_goal_judge`）

### 3.1 样本契约（`evals/dataset/brain_goal_judge/schemas.py`）

```python
class JudgeCase(BaseModel):
    case_id: str
    request: FromHarnessToBrainToolJudgeReq   # 生产信封原样冻结
    achieved: bool                             # 真值；只给 scorer
    layer: Literal["run", "episode"]           # 采自哪一层的判定
    truth_source: Literal["mechanical", "human"]
    truth_note: str                            # 机械：check_id + 证据；人工：依据
    hard_negative: Literal["off_by_one", "right_map_wrong_tile",
                           "wrong_dialog_line", "looks_done", ""] = ""
    origin: str                                # 采集来源：run_id / 样本 id
```

`v1/` 的 4 条补齐新字段（`layer="episode"`、`truth_source="human"`）后原样进 `v2/`。

### 3.2 采集与真值

- 现场来自 agent_goal_run 真机 run 的 **run 层与 episode 层**判定调用（§五的录制器）。task 层判定的判据由拆解器现写，没有机械对照，**不采**。
- 真值：同一段历史跑 `evals/scorers` 的机械判据（样本的 `check_id`）；机械判不了的（`unjudgeable`）由人工标并写 `truth_note`，否则不入集。
- 难负例：从机械判负的现场里按 §3.1 的四类挑；数量不够的类别，在对应起点存档上用人工按键序列造现场（再走同一个录制器）。

### 3.3 评分

现行四格 scorer 不变；新增 metrics：`false_positive_rate = FP/(FP+TN)`、`false_negative_rate = FN/(FN+TP)`、`judged_count`；按 `hard_negative` 与 `layer` 用 `grouped` 出分组数。

---

## 四、S4 choose 节点测评（`brain_choose_action`）

### 4.1 样本契约（`evals/dataset/brain_choose_action/schemas.py`）

```python
class ActionMatcher(BaseModel):
    """可接受动作的一条：按键名，或脚本名 + 参数约束。"""
    key: str | None = None
    script: str | None = None
    args: dict[str, str | int] | None = None   # None = 该脚本任意参数都可接受
    # 契约：key 与 script 恰好一个非空

class ChooseCase(BaseModel):
    case_id: str
    request: FromHarnessToBrainToolChooseOnceReq  # 生产信封原样冻结（截图在 memories 的帧里）
    state: str                                     # 同一时刻的存档，相对版本目录
    acceptable: list[ActionMatcher]                # 非空
    scene: str                                     # 该帧 TaskScene，用于分组
    tags: list[Literal["read_screen", "answer_in_memory", "after_failure"]] = []
    label_source: Literal["replay", "human"]
    label_note: str
    origin: str
```

### 4.2 solver / scorer（`evals/solvers/brain_choose_action.py`、`evals/scorers/brain_choose_action.py`）

- solver：`BrainTool.build(text=<text_model>).chooser.choose(case.request)`——与生产同一条渲染、重试、规范化路径；型号缺省取 `evals/config.json` 的 `models.text_model`，`-T text_model=` 可覆盖。`MaxRetriesExceeded` 记为"解析失败"（被测结论）；网络 / 密钥失败上抛为 sample error。
- scorer 三列（C / I / N）：`acceptable`（选中的动作命中任一 matcher）、`legal`（在掩码内；生产 `BrainPort.choose` 的后置条件已保证，出现 I 即为 bug）、`parsed`；按 `scene` 与 `tags` `grouped`。

### 4.3 可接受集合的标注（J1 暂定）

1. **按键自动预标**：对样本存档，把 `request.space` 里每个启用的按键各重放一次（`evals/solvers/world_case.start_world` + 单键 `step`），按**推进谓词**判这一键是否可接受：
   - 走路类 task：执行后到 task 判据坐标的曼哈顿距离变小或已到达；
   - 对话：对话文字推进或对话框关闭；
   - 选单：光标移向判据要求的项，或进入目标界面；
   - 判据不属于以上三类的样本不自动标，转人工。
2. **脚本人工标**：掩码里的脚本由人按判据决定是否可接受、参数约束到什么程度。
3. **人工审**：预标结果全部过一遍；`label_source` 记最终来源，改动过的标 `human`。

### 4.4 难点标签的判定

- `read_screen`：`request.obs` 的解码字段切不全（`ScreenText.covered=False` 或数量框、队伍列表、起名键盘），答案只在 `screen` 里；
- `answer_in_memory`：标注人确认正确动作依赖 `memories` / `knowledge` / `episode_memories` 的内容；
- `after_failure`：`request.last_result` 报失败。

---

## 五、现场录制器（J2 暂定）

录制器是**造数据**的代码（choose、judge 两个数据集共用），放 `evals/dataset/capture/`（不是数据集，没有版本目录）：

```
evals/dataset/capture/
├── recorder.py     RecordingChooser / RecordingJudger：实现 ChoosePort / JudgePort，
│                   持有被包装的生产对象 + GameToolPort + 落盘目录；
│                   每次调用：① game.save_state(<目录>/<seq>.state) ② 写请求信封 JSON
│                   ③ 原样转发给生产对象、把响应一并写下；不改变返回值与异常
└── __init__.py
```

- 装配：只在 `python -m evals agent_goal_run run-one --capture <目录>` 时，由 run-one 在 `build_branch` 里把 `deps.episode.task.chooser`、`deps.episode.judger`、`deps.judger` 换成录制器；不传 `--capture` 时 run-one 行为与现在逐字节相同。
- 生产代码零改动；录制器只经公开端口（`ChoosePort` / `JudgePort` / `GameToolPort.save_state`）工作。
- 落盘只是**原始现场**，不是数据集：经标注工具（`evals/dataset/<名>/build/`）补真值、挑选后才冻结进 `v<n>/`。

---

## 六、测试（用法示范）

| 测试文件 | 内容 |
|---|---|
| `tests/test_evals_tasks.py` | 公开 task 恰为六个新名（S4 后七个）；`@task` 函数名 = 注册名 |
| `tests/test_evals_datasets.py`（新） | 每个数据集包 `load()` 返回非空类型化样本；版本目录自包含（样本引用的文件都在版本目录下）；`TakeoverCheck` 每个 `kind` 一正一反 |
| `tests/test_evals_capture.py`（新） | 录制器包装假 chooser / judger：返回值与异常透传不变，落盘的信封可被 `ChooseCase.request` / `JudgeCase.request` 原样解析 |
| `tests/test_evals_choose.py`（新） | `ActionMatcher` 命中规则；scorer 三列在构造的 `ChooseCase` 上的结果 |

不连网、不调真实模型；需要 ROM 的测试在没有 ROM 时跳过（与现有约定一致）。

## 七、不做

intent 第八节所列；另外本 spec 不定 choose / judge 的样本**具体内容**（属于采集与标注工作，plan 里排），不改 agent_goal_run 的评分。
