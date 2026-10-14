# spec —— `brain_choose_action`：契约、数据、指标与交接

> 流程位置：intent.md（`brain-choose-action-intent.md`）→ **spec.md（本文）** → plan.md → PR → production
> 状态：**v1 草案，待确认**
> 起草：2026-10-13
> 依据：`brain-choose-action-intent.md`；现状以 2026-10-13 仓库为准（HEAD `32bb1cc`，第二阶段完成）
> 约束：`pokemon_agent/`（含 prompt、brain、world）零改动；只动 `evals/`、`tests/`、文档。

---

## 〇、暂定项（按推荐写入，可推翻）

| 编号 | 暂定方案 | 影响小节 |
|---|---|---|
| D1 | 目录 `evals/brain_choose_action/`，B 类，入口 `python -m evals.brain_choose_action`，结构同 `evals/world_script_execute/`（数据用 `dataset/` 子包） | §四 |
| D2 | 一个 `ChooseCase` 一个 `LLMTestCase`；指标 `acceptable`、`parsed`、`legal`，另有按场合、按标签的 `acceptable.<名>`；全部确定性，不调 LLM | §二 |
| D3 | 可接受集合 = 若干 `ActionMatcher`。按键 matcher 可带连按上限；脚本 matcher 带参数约束。按键链**每一段**都命中才算命中 | §一 |
| D4 | 数据两路：A 冻结帧（`frames/v2` 拼现场）、B 自跑采集（`.state` + 录制器）。同一种 `ChooseCase` 格式，`source` 区分 | §三 |
| D5 | 标注：规则预标 + 人工全审；脚本 matcher 全部人工标；`label_source` 记最终来源 | §三 |
| D6 | v1 四类场合：`walk`、`dialog`、`start_menu`、`battle_menu`，各 8–10 条，共约 35 条；难点标签不设配额 | §三 |
| D7 | 录制器放 `evals/common/recorder.py`（`brain_goal_judge` 以后也可复用）；采集入口放 `evals/brain_choose_action/dataset/build/collect.py`，只在人工运行时装配，生产路径不变 | §三 |
| D8 | 不做执行验证；不依赖 `agent_short_goal_run` 的旧存档 | §八 |
| D9 | 模型缺省取 `evals/config.json` 的 `models.text_model`，`--text-model` 覆盖；缺键即报错（沿用 `runconfig` 约定） | §二 |

---

## 一、数据契约

### 1.1 `ActionMatcher` 与 `ChooseCase`（`evals/brain_choose_action/dataset/schemas.py`）

```python
class ActionMatcher(BaseModel):
    """可接受动作的一条：按键，或脚本 + 参数约束。key 与 script 恰好一个非空。"""
    key: str | None = None
    max_times: int | None = None              # 仅按键：连按次数上限；None = 不限
    script: str | None = None
    args: dict[str, str | int] | None = None  # 仅脚本：列出的参数必须相等；None = 任意参数

class ChooseCase(BaseModel):
    case_id: str
    request: FromHarnessToBrainToolChooseOnceReq  # 生产信封原样冻结
    acceptable: list[ActionMatcher]                # 非空
    scene: str                                     # TaskScene 的值，用于分组
    tags: list[Literal["read_screen", "answer_in_memory", "after_failure"]] = []
    source: Literal["frame", "collected"]
    label_source: Literal["rule", "human"]
    label_note: str
    origin: str                                    # 帧 id，或采集目录与步号
```

构造期断言（pydantic 校验）：`ActionMatcher` 的 key 与 script 恰好一个非空；`max_times` 仅与 key 同用，`args` 仅与 script 同用；`acceptable` 非空；`scene` 是合法 `TaskScene`。

### 1.2 命中规则（`compare.py`，纯函数，不依赖 deepeval）

`matches(action: Action, acceptable: list[ActionMatcher]) -> bool`：
- **脚本动作**（`action.script` 非空）：存在一条 matcher，`script` 与脚本名相等，且 `args` 里列出的每个参数在 `action.script.args` 中逐项相等；`args` 为 `None` 则任意参数。
- **按键链**（`action.sequence` 非空）：链中**每一段**都命中某条按键 matcher——`segment.name == matcher.key`，且 `matcher.max_times is None or segment.times <= matcher.max_times`。
- 其余一律不命中；按键动作不会命中脚本 matcher，反之亦然。

`is_legal(action, space) -> bool`：按键链每段的 `name`、脚本的 `script.name` 都必须满足 `space.enabled(name)`。**`mask` 只认 world 给出的那一份**（`world/action_space.py::compute_action_space`，键与脚本同一命名空间）；评测不自己拼、不依赖别处产出的掩码。

### 1.3 各场合的动作形状

数据形状上，动作空间是**一个命名空间**：`mask`（名字 → 可用，**只由 world 产出**）加 `entries`（`kind` 为 `key` 或 `script`），模型同权选择，不分按键空间与脚本空间。但**内容仍随场合不同**：仅开放脚本的场合（`SCRIPT_ONLY_SCENES`）`names` 为空、只给脚本；开放按键的场合给按键，并可附带该场合的脚本。

| 场合 | 开放什么 | 可接受集合的形状 |
|---|---|---|
| `walk` | 方向键与 `a` 等按键（另有可选脚本） | 按键 matcher；走向目标的方向键 |
| `dialog` | 按键 | 通常只有 `a`（`max_times=1`）；对话里的 YES/NO 依赖目标，人工标 |
| `start_menu` | 按键 | 光标已在目标项 → `a`；否则朝目标项的方向键，`max_times` 不超过光标到目标的距离 |
| `battle_menu` | **仅脚本**（`SCRIPT_ONLY_SCENES`，不给按键） | 脚本 matcher；脚本名与参数约束以该场合 `ActionSpace.entries` 里的真实签名为准 |

`walk` 里若脚本也是合理答案（如 `walk_to`），人工可补脚本 matcher。

---

## 二、评测契约

### 2.1 solver（`evals/brain_choose_action/solver.py`）

`choose_case(case, chooser) -> ChooseRun`
- `chooser` 为 `BrainTool.build(text=<text_model>).chooser`，与生产同一条渲染、重试、规范化路径；`chooser.choose(case.request)` 返回动作。
- 模型缺省取 `models.text_model`；模型名不认识时构造当场炸。
- 结果 `ChooseRun`：`action: Action | None`、`failure: str`（`MaxRetriesExceeded` 的摘要）、`calls`（模型调用账，原样保留便于排查）；契约：`action` 与 `failure` 恰好一个有值。
- 网络、密钥、网关不通（不是解析失败）：该样本不造结果，抛 `ProviderUnreachable`，由入口捕获、打印、不进分母。判别方式沿用 `episode_vision_read`：调用账里有 `error`。
- 并发：线程池，`--workers N`，默认 4。

### 2.2 用例（`evals/brain_choose_action/cases.py`）

`build_cases(cases, runs) -> list[LLMTestCase]`：
- `name=case_id`，`input` 为栈顶目标（`request.goals[-1].goal`）；
- `actual_output`：JSON `{"describe": Action.describe(), "action": <结构化>}`，或 `{"failure": "..."}`；
- `expected_output`：`acceptable` 的 JSON；
- `additional_metadata`：`{"scene": ..., "tags": [...], "mask": <space.mask>}`（`legal` 用）。

### 2.3 指标（`scorer.py`，均不调 LLM，`evaluation_model = None`，`threshold = 1.0`，构造参数以同名属性保存）

| 指标名 | 构造 | 规则 |
|---|---|---|
| `acceptable` | 无 | 解析失败 → 0.0；`matches` 为真 → 1.0，否则 0.0；`reason` 写动作与期望 |
| `parsed` | 无 | `actual_output` 无 `failure` → 1.0，否则 0.0 |
| `legal` | 无 | 解析失败 → 抛 `MissingTestCaseParamsError` 跳过；否则 `is_legal` 为真 → 1.0，否则 0.0 |
| `acceptable.<组>` | `AcceptableBy(group)` | 只挂 `scene == 组` 或 `组 ∈ tags` 的用例，其余抛 `MissingTestCaseParamsError`；计分同 `acceptable` |

`<组>` 的取值：数据里出现过的全部场合与标签，由入口扫描生成，不硬编码。

整体 Pass Rate = 一条用例所有已挂指标都过。读法：`acceptable` 看 Pass Rate；`acceptable.<场合>` 看分组通过率；`legal` 失败即为 bug，要立刻查。

### 2.4 入口（`__main__.py`）

```powershell
python -m evals.brain_choose_action [--text-model M] [--scene S]... [--tag T]... [--case ID]... [--workers 4]
```

- 经 `evals.common.run.run_evaluation`（第二阶段已有）输出，`results_folder="eval_results/brain_choose_action"`，`hyperparameters={"dataset": "v1", "cases": n, "text_model": ...}`。
- 过滤条件给了不存在的 id、场合或标签：当场报错，不静默跑空集。
- 不通样本在末尾打印一行（id 与原因），不设专用退出码；有失败用例退出码 1。

---

## 三、数据：制作与标注

### 3.1 A 路：冻结帧（`dataset/build/from_frames.py`）

输入：`evals.dataset.frames.load("v2")` 的帧；`dataset/build/goals.jsonl`（人工写：`sample_id`、`goal`、`criteria`）。

对被选中的每一帧：
1. 取 WRAM 快照与地图：`snapshot_of(sample)`、`read_terrain(memory)`、`read_screen_text(memory)`；
2. `observe_task(terrain, text, png, memory=…, rom=ROM.read_bytes(), closed=False)` 得 `TaskObservation`（`evals.decode.solver` 里已有等价的读取序列可参照）；
3. `compute_action_space(observation, all_actions)` 得 `ActionSpace`（`world/action_space.py`，掩码的唯一出处）；`all_actions` 取与生产一致的全部按键名（`pyboy_world` 里的 `ALL_BUTTONS`）；
4. 拼 `FromHarnessToBrainToolChooseOnceReq(goals=[Goal(goal, criteria)], obs, space, memories=[], last_result="", knowledge="", episode_memories="", human_note="")`。

选帧：按 `ScreenSample.label.scene` 取 `walk`、`dialog`、`start_menu`、`battle_menu` 各 8–10 帧，要求 `label_checked` 且 `wram` 非空，并且观测装配出的 `TaskObservation.scene` 与目标场合一致（不一致的丢弃并记录）。

**S0 前置验证：** 上述 1–4 步对被选中的帧全部能跑通，且动作空间非空（`names` 或可用脚本至少一个）。跑不通就停下来报告，不要为了凑数改解码。

### 3.2 B 路：自跑采集（用户本机）

- 录制器 `evals/common/recorder.py`：`RecordingChooser(inner: ChoosePort, out_dir)` 实现 `ChoosePort`；每次 `choose` 调用：① 把请求信封 JSON 写入 `out_dir/<序号>.request.json` ② 转发给 `inner` ③ 把响应或异常摘要写入 `<序号>.response.json`；返回值与异常原样透传，不改任何行为。
- 采集入口 `dataset/build/collect.py`：`python -m evals.brain_choose_action.dataset.build.collect --state <.state> --goal <目标> --criteria <判据> --steps N --out <目录>`。装配沿用 `evals.agent_short_goal_run.dataset.build.pack` 里 `build_real(ROM, state, ...)` 的方式，只把 task 层的 `chooser` 换成 `RecordingChooser`；跑 N 步或目标完成即停。需要 PyBoy 与 ROM，**由用户本机运行**，且串行（一次一个模拟器）。
- 采集出来的是**原始现场**，不是数据集；经 §3.3 标注后才冻结进 `v1/`。
- **前置：掩码已统一到 world**（CHANGELOG 442）：进程内路径的动作空间也由 `compute_action_space` 产出，采集录下的 `request.space` 的 `mask` 已含全部按键，无需另行重算。
- 起点 `.state` 来源：`evals/dataset/world_script_execute/v1/states/` 或 `evals/agent_short_goal_run/dataset/v1/states/` 下的原始 `.state`；**不使用**其中的 `archives/`（旧存档当前被拒载）。

### 3.3 标注（`dataset/build/label.py`）

输入：A 路装配结果或 B 路采集目录；输出：`cases_draft.jsonl`（`label_source="rule"`），人工审后另存为 `v1/cases.jsonl`。

规则预标（只作用于按键场合；输入是 §3.1 的观测与屏幕文字解码）：
- `dialog`：`a`，`max_times=1`。若 `overlay` 是选择框（YES/NO 等），不预标，留给人工。
- `start_menu`：从 `facts.options` 与 `facts.cursor` 得光标所在项下标，从目标描述得目标项下标：相等 → `a`；否则朝目标的方向键（`up`/`down`），`max_times = |下标差|`。目标项不在选项里 → 不预标。
- `walk`：目标格由 `goals.jsonl` 给出相对当前位置的坐标；在 `read_terrain` 给出的可走性上做广度优先，求使到目标格路径长度变短的方向键集合。**若 `read_terrain` 的可走性不足以做路径计算，walk 一类整体改为人工标，并在报告里说明。**
- `battle_menu`、所有脚本 matcher：不预标，全部人工标；参数约束到什么程度由标注人决定。

人工审：**每一条**都要过目；改动过的 `label_source` 记 `human`，`label_note` 写依据。未审过的草稿不得进 `v1/`。

难点标签判定：
- `read_screen`：`obs` 的解码字段切不全（`menu_decode_complete is False`，或数量框、队伍列表、起名键盘）；
- `answer_in_memory`：标注人确认正确动作依赖 `memories` / `knowledge` / `episode_memories`；
- `after_failure`：`request.last_result` 非空且报失败。

### 3.4 规模

v1 约 35 条：`walk`、`dialog`、`start_menu`、`battle_menu` 各 8–10。A 路为主；B 路按需补充，使后两类标签至少各出现数条（不设硬配额）。

---

## 四、目录与改动清单

```
evals/brain_choose_action/
├── __init__.py
├── __main__.py       # 入口（§2.4）
├── cases.py          # build_cases
├── solver.py         # ChooseRun、choose_case、ProviderUnreachable
├── compare.py        # matches、is_legal（不依赖 deepeval）
├── scorer.py         # 指标与 build_metrics
└── dataset/
    ├── __init__.py   # 导出 ChooseCase、ActionMatcher、load
    ├── schemas.py
    ├── loader.py     # 读 v1/cases.jsonl；缺失、重复 id 抛 DatasetError
    ├── build/
    │   ├── from_frames.py
    │   ├── collect.py
    │   ├── label.py
    │   └── goals.jsonl
    └── v1/cases.jsonl
evals/common/recorder.py
```

- 新增公开任务：`evals/registry.py` 加 `"brain_choose_action": TaskEntry(kind="deepeval", entry="evals.brain_choose_action")`，公开任务由六个变七个。
- 修改：`tests/evals/test_evals_tasks.py` 的"公开任务"断言改为七项；`AGENTS.md` 与 `CLAUDE.md`（保持同步）、`docs/spec/evals/SPEC.md` 的任务清单；`docs/eval/tasks-intent.md` 第四节、`tasks-spec.md` 第四、五节改为指向本文；`CHANGELOG.md` 每个提交一条新条目。
- 复用（不改）：`evals/common/run.py`、`evals/dataset/{io,errors}.py`、`evals/dataset/frames/`、`evals/runconfig.py`。
- 数据读取沿用 `evals/dataset/io.py` 的 `read_models`、`version_directory`；loader 的形状同 `evals/world_script_execute/dataset/loader.py`。

---

## 五、测试（用法示范）

| 测试文件 | 内容 |
|---|---|
| `tests/test_evals_choose.py`（新） | `matches` 的命中规则（按键链逐段、`max_times`、脚本参数子集、形状不符）；`is_legal`；三个指标与分组指标在构造的 `ChooseCase` 与 `ChooseRun` 上的结果；解析失败时 `legal` 跳过 |
| `tests/test_evals_choose_data.py`（新） | `v1/cases.jsonl` 每条可解析；`acceptable` 非空；`label_source` 都已审；`request` 里的动作空间非空；场合集合恰好是 v1 的四类 |
| `tests/test_evals_capture.py`（新） | `RecordingChooser` 包装假 chooser：返回值与异常透传不变；落盘的请求信封可被 `FromHarnessToBrainToolChooseOnceReq` 原样解析 |
| `tests/evals/test_evals_tasks.py` | 公开任务七项 |

不连网、不调真实模型；用假 chooser（按预设返回动作）跑完整流程，覆盖命中、未命中、解析失败、越权四种结果。

---

## 六、验收

1. **数据**：`v1/cases.jsonl` 约 35 条，四类场合各 8–10；每条 `request` 可被生产信封原样解析；`acceptable` 非空；每条都经人工审（无 `label_source` 为草稿的条目）。
2. **假 chooser 全流程**：命中、未命中、解析失败、越权四种结果与预期一致；整体 Pass Rate、各指标 Total 与数据相符（`acceptable` 与 `parsed` 的 Total 等于样本数；`legal` 的 Total 等于样本数减解析失败数）。
3. **真实模型一次**：用 `models.text_model` 跑 v1 全量，输出整体 Pass Rate、`acceptable`、`parsed`、`legal` 与 `acceptable.<场合>`；失败时退出码 1；不通样本被列出。
4. **可重测**：`--text-model` 换一个模型，同一批样本可直接重跑，无需重新采集。
5. **录制器**：测试通过；若做了 B 路采集，至少有一份采集目录能被 `label.py` 读成草稿。
6. 全量 `pytest` 通过；`ruff check` 与 `ruff format --check` 通过。
7. `pokemon_agent/` 零改动（`git diff --stat` 可证）；仓库内无对旧 choose 设计（Inspect 版 solver/scorer）的活引用。
8. 运行产物（`eval_results/brain_choose_action/`）被 `.gitignore` 覆盖。

---

## 七、风险

- **R1 冻结帧装配**：`observe_task` 需要 `terrain`、`text`、`png`、`memory`、`rom`，其中 `closed`、地图是否稳定等细节可能让部分帧装配出的场合与标注不一致；S0 必须先验证。
- **R2 walk 的路径规则**：可走性是否足以做 BFS 不确定；不足就整类改人工标（§3.3）。
- **R3 `battle_menu` 的脚本签名**：参数名与取值以 `ActionSpace.entries` 为准，标注前要先读出该场合的真实签名；脚本参数约束写得过严会误判，过松会漏判。
- **R4 样本数小**：每类 8–10 条，通过率波动大；v1 的结论只用于比较同一批样本上的相对变化，不作绝对结论。
- **R5 目标文字的主观性**：A 路的目标由人写，写法会影响模型表现；`goals.jsonl` 要随数据一起冻结，改目标即视为新版本。
- **R6 模型调用成本**：一次全量约 35 次调用，量很小；重测、多模型对比的费用随次数线性增加。
- **R7 B 路依赖本机环境**：采集需要 PyBoy、ROM；失败不影响 A 路交付。

---

## 八、非目标

- 不做执行验证（把所选动作在模拟器上真跑一遍）；不引入 LLM 判分。
- 不改 prompt、brain、world 的任何生产代码。
- 不覆盖 v1 之外的场合（商店、背包、PC、队伍、起名、学招、战斗文字等）。
- 不修复 `agent_short_goal_run` 的旧存档；不依赖其 `archives/`。
- 不迁移或改动别的任务。

---

## 九、交接清单（给执行者）

每步一个提交，提交信息和 CHANGELOG 沿用仓库格式；先读 `docs/eval/brain-choose-action-intent.md` 与本文，并参照 `evals/world_script_execute/`、`evals/memory_store_recall/`、`evals/decode/` 的结构与 `evals/common/run.py`。

**P0（确认前置）**：`git status` 工作区干净，HEAD 含 CHANGELOG 442（`mcpclient/game_tools.py` 里已没有 `_mask`，改为 `_action_space`）；否则停止并报告。

**S0 验证装配（不写入仓库）**
1. 写一次性脚本：对 `walk`、`dialog`、`start_menu`、`battle_menu` 各挑若干 `label_checked` 且有 WRAM 的帧，按 §3.1 装出 `FromHarnessToBrainToolChooseOnceReq`；
2. 报告：每类能装出多少帧、`TaskObservation.scene` 与标注是否一致、`space` 是否非空（按键场合 `names` 非空，仅脚本场合 `entries` 非空）、`battle_menu` 场合的脚本签名（名称与参数）。
3. 确认 `compute_action_space` 给出的 `mask` 覆盖全部按键与本场合脚本（不可用的键显式为 `False`）。
4. **停止条件**：任一类场合不足 8 帧，或装配的场合大面积不一致——停下来报告，不要改解码。

**S1 契约与评测骨架**
1. 建 `dataset/schemas.py`、`compare.py`（`matches`、`is_legal`）、`solver.py`、`cases.py`、`scorer.py`、`__main__.py`、`dataset/loader.py`；
2. 写 `tests/test_evals_choose.py`，用假 chooser 与手造 `ChooseCase` 走完整流程（命中、未命中、解析失败、越权）；
3. 暂不注册、不放数据。

**S2 A 路数据**
1. 实现 `from_frames.py`、`label.py`，写 `goals.jsonl`（每类 8–10 条目标，目标文字要能只看一帧判断是否达成）；
2. 产出 `cases_draft.jsonl`，**交给用户人工审**；审完才进 `v1/cases.jsonl`；
3. 加数据测试 `tests/test_evals_choose_data.py`。
4. **停止条件**：walk 的路径规则做不出来（R2）→ 报告，改为整类人工标，由用户决定。

**S3 录制器与 B 路采集入口（B 路数据由用户本机跑）**
1. 实现 `evals/common/recorder.py`、`dataset/build/collect.py`，写 `tests/test_evals_capture.py`；
2. 在没有 ROM 的环境里，只验证录制器的单元测试，不跑真模拟器；
3. 把采集命令交给用户，由其在本机运行并反馈采集目录。

**S4 注册与收尾**
1. `registry.py` 加一项；`tests/evals/test_evals_tasks.py` 改七项；
2. 同步 `AGENTS.md`、`CLAUDE.md`、`SPEC.md`；`tasks-intent.md`、`tasks-spec.md` 里对应章节改为指向本文；
3. 假 chooser 全流程跑一遍，并（**经用户确认调用费用后**）用真实 text_model 跑一次 v1，保存输出到 `eval_results/`；
4. 全量 `pytest`、`ruff` 通过。

**停止条件汇总**：S0 的场合或帧数不足；人工审未完成；`read_terrain` 无法支撑路径规则；任何需要改 `pokemon_agent/` 才能继续；任何一步需要真实模型调用而用户尚未确认费用。遇到就停下来报告，不要改比较规则或降低样本要求去凑通过。

**完成条件**：验收 1–8 全部满足；CHANGELOG 写明本任务的口径（指标定义、命中规则、v1 范围与不做执行验证）。
