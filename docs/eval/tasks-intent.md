# intent —— 测评 task 改名 + choose 节点测评 + judge 扩容

> 流程位置：**tasks-intent.md** → tasks-spec.md → tasks-plan.md → PR → production
> 前置：`docs/eval/intent.md`（测评体系总意图）、`docs/spec/evals/SPEC.md`（现行六个 task）
> 范围：三项，按顺序做——① 改名 ② choose 节点测评 ③ judge 扩容。其余节点不加 task（见「不做」）。

---

## 一、一句话意图

**看名字就知道每个 task 测的是哪个模块的哪个节点；补上调用最频繁的决策节点 choose；把 judge 从示范用例扩成能报出可信假阳 / 假阴率的测评。**

## 二、为什么现在做

1. **名字不表意。** `decode` / `vision_perceive` / `world_actions` / `memory` / `judge` / `e2e` 看不出测的是 world 还是 brain、是哪个节点。名字含糊的代价已经出现过一次：`screen_interpret` 听上去像在测读屏，实际不对应任何生产调用，输入即答案（392 已删）。
2. **choose 没有节点级测评。** task 层每按一键调一次，是全链路调用最多的模型节点；读屏规则 `READ_SCREEN` 也只在它（和 judge）的 prompt 里生效。现在只能从 e2e 的成败间接看到它，失败分不清是"没读懂屏幕"还是"读懂了但选错"。
3. **judge 只有 4 条示范用例。** 成功率的唯一来源是 judge（`docs/eval/intent.md` §二-1：机械复核 124 次，judge 假阳 16、假阴 3）；4 条用例报不出任何区间，也覆盖不到会出事的那几类情形。

## 三、改名（第一项，后两项按新名落地）

**规则：`模块_节点_动作`**——模块是被测节点所在的模块（world / brain / memory / agent），节点与动作说明测哪一步。`decode` 不改（用户定）。

| 现名 | 新名 | 测的是 |
|---|---|---|
| decode | decode（不改） | world 从 RAM 机械解码场合、读屏文字、接管视图、地形 |
| vision_perceive | `episode_vision_read` | episode / run 档取帧的纯视觉子节点 `perceive_visual` |
| world_actions | `world_script_execute` | world 脚本（常规 + 接管）在真模拟器上执行 |
| memory | `memory_store_recall` | 记忆写入、读回与检索 |
| judge | `brain_goal_judge` | brain 判定目标是否达成（第五节扩容的就是它） |
| e2e | `agent_goal_run` | 完整系统跑完一个目标 |
| （新增） | `brain_choose_action` | brain 选一步动作（第四节） |

**改动面**：task 目录与 `@task` 函数名、`evals/tasks/registry.py`、`python -m evals run <名>`、引用它们的测试、`docs/spec/evals/SPEC.md`、AGENTS.md / CLAUDE.md 的 task 清单、CHANGELOG。

**旧日志**：改名前落盘的 `.eval` 日志已全部删除（不保留旧名的结果）。

**不改**：被测系统代码；各 task 的评分口径。

### 数据集重整：统一放到 `evals/dataset/`

现在数据散在四处：`evals/data/v1/`（e2e 起点）、`evals/data/frames/`（帧集 + 真值，和构建脚本混在同一个包里）、各 task 目录里（`judge/dataset.jsonl`、`memory/dataset.json`、`world_actions/` 的十几个 `*_batch_*.py` 用例文件），以及 `experiment/experiment_states/`（world_actions 用的存档，同时也被 `experiment/tasks.py` 用）。看目录分不清哪些是数据、哪些是代码、哪份数据属于哪个 task。

**规则**：

1. 一级目录按**使用它的 task 名**（与改名后的名字一致）；多个 task 共用的数据单独一个目录，名字说清它是什么（`frames/`）。
2. 每个一级目录是一个包，装**这份数据的契约与读取代码**：`schemas.py`（样本的数据契约——数据集产出它，所以归这里，不归 task）+ `loader.py`（读冻结文件、核冻结、挂真值），出口只导出读取函数与样本类型。task 只经这个出口拿数据，不知道文件在哪、什么格式。task 自己运行时的记录（`StoreModel` 等）仍留在 task 目录。
3. 包下的二级目录是**版本**（`v1/`、`v2/`…），只放冻结文件：冻结后不改，要改就出新版本。
4. 每份数据**自包含**：用到的存档拷进本数据集目录，不跨目录引用 `experiment/` 下的文件（`experiment/` 留给它自己的实验）。

**目标布局**：

```
evals/dataset/
├── frames/                        ← decode、episode_vision_read 共用
│   ├── schemas.py / loader.py     ScreenSample / FrameTruth；读帧集 + 挂已审核真值
│   └── v2/                        samples.jsonl（1045 帧）+ truth.jsonl
├── agent_goal_run/
│   ├── schemas.py / loader.py     EvalSample / rubric；读样本 + 核冻结哈希
│   └── v1/                        samples.jsonl、states/、archives/、coverage.md、rubric.json
├── world_script_execute/
│   ├── schemas.py / loader.py     ScriptCase / ScriptExpect；读 cases.jsonl
│   └── v1/                        cases.jsonl（106 例：常规 + 接管）+ states/（用到的存档）
├── memory_store_recall/
│   ├── schemas.py / loader.py
│   └── v1/                        dataset.json（现有 3 条记录 / 3 个查询）
├── brain_goal_judge/
│   ├── schemas.py / loader.py     JudgeCase
│   └── v1/                        dataset.jsonl（现有 4 条）；扩容后出 v2
└── brain_choose_action/           （新建，同一形状）
```

**搬迁映射**：

| 现位置 | 新位置 |
|---|---|
| `evals/data/frames/dataset/v2/samples.jsonl` + `evals/data/frames/truth.jsonl` | `evals/dataset/frames/v2/` |
| `evals/data/v1/*` | `evals/dataset/agent_goal_run/v1/` |
| `evals/tasks/world_actions/` 下的用例（`cases.py`、`regular_batch_*.py`、`takeover_batch_*.py`、`takeover_cases.py`）+ 用到的 `experiment/experiment_states/*` | `evals/dataset/world_script_execute/v1/` |
| `evals/tasks/memory/dataset.json` | `evals/dataset/memory_store_recall/v1/` |
| `evals/tasks/judge/dataset.jsonl` | `evals/dataset/brain_goal_judge/v1/` |
| 读取代码：`evals/data/loader.py`、`evals/data/frames/{schemas,truth}.py` 与 `build.py::load_samples`、`evals/core/frames.py`、各 task 里读 `dataset.json(l)` 与 import 用例的代码 | 各自数据集包的 `loader.py`；样本契约（`ScriptCase`、`JudgeCase`、`EvalSample`…）移到对应包的 `schemas.py` |

## 四、choose 节点测评（`brain_choose_action`）

**被测对象**：`BrainTool.choose` 的**一次**决策——生产 prompt `decide_action` 的渲染 + `BrainPort.choose` 的解析与合法性校验 + 模型。不经 harness 循环、不执行动作。

**样本 = 一次真实决策现场**：

- 那一刻的请求信封 `FromHarnessToBrainToolChooseOnceReq`（`goals` / `obs` / `space` / `memories` / `last_result` / `knowledge` / `episode_memories` / `human_note`）冻结成 JSON。冻结的是**信封**而不是渲染好的 prompt 字符串——prompt 改了要能拿同一批样本重测。截图随 `memories` 里的帧一起冻结（`BrainTool` 从记忆里拼 `images`）。
- 同一时刻的模拟器存档（定真值用，见 J1）。

**真值 = 可接受动作集合**，不是唯一答案：同一个画面往往有几种合理的下一步（绕左绕右都行）。

**评分**：选中的动作在集合里 = 对；越权动作（不在掩码里）、解析失败各单列一列；按场合（walk / dialog / battle_menu / shop …）与难点标签分组出数。难点标签至少包括：

- **需读整屏原样**：解码切不全（队伍列表、数量框、起名键盘、切不全的选单），答案只在 `screen` 里——这一组替代被删掉的读屏探针；
- **答案在记忆里**：正确动作依赖 `memories` / `knowledge` / `episode_memories` 里的信息；
- **上一步失败后**：`last_result` 报失败、要换策略的那一步。

**样本来源**：真机 run 里采集决策现场（见 J2），起点用 e2e 现有的 20 个存档；e2e 跑出来的选错动作的现场，确认后入集。

## 五、judge 扩容（`brain_goal_judge`）

**被测对象不变**：生产判定器读 `FromHarnessToBrainToolJudgeReq`（`goal` / `history` / `task_memories` / `task_table` / `episode_memories` / `allow_interrupt`），给出达成与否和理由。

**样本 = 一次真实判定现场**：冻结的 `JudgeReq` + 真值 `achieved`。标签只给 scorer，不进判定器。

**真值来源**：**机械判据优先**——同一段历史上跑 `evals/scorers` 的机械判据（e2e 已有 18 条 `@rule`，按 `check_id`）；机械判不了的由人工标并注明依据。不从判定器自己的文字反推。

**样本来源**：e2e 真机 run 里 `judge_call` 的现场（采集方式同 choose，见 J2）。正负例都要有，并**专门收难负例**——这才是假阳的来源：

- 差一格到达（坐标近、判据要求的那一格没到）；
- 地图对、坐标不对；
- 对话里出现过别的话，不是判据要的那一句；
- 画面像完成了，但目标那一步没发生（如进了战斗但不是野生遭遇）。

**评分**：现行 TP / FP / FN / TN 不变，增加假阳率、假阴率与样本数（N 不进分母）；按难负例类别分组。

## 六、待拍板（进入 spec 前必须定）

| 编号 | 问题 | 选项 |
|---|---|---|
| J1 | choose 的可接受集合怎么定 | (a) 人工逐条标；(b) 在存档上把掩码里的每个候选动作都重放一遍，按规则自动判"推进了没有"（离目标更近、对话推进、换图、触发期望事件），人工抽审；(c) 自动预标 + 人工全审 |
| J2 | 决策 / 判定现场怎么采 | (a) 在 `BrainTool.choose` / `judge` 调用处加一个默认关闭的采集开关，写信封 + 存档（要改生产代码）；(b) 让 trace 的 `choose_call` / `judge_call` 账带上完整信封，再离线反解（改 trace 内容，需商定）；(c) evals 侧包一层录制用的 BrainTool，只在采集时装配 |
| J3 | 首版规模与配比 | choose 每个场合、每个难点标签各多少条；judge 正负比例、每类难负例至少多少条 |
| D1 | 数据**生产**工具放哪（读取代码已定：进各数据集包） | 采集 / 构建 / 打包 / 审核工具（`pack.py`、`frames/` 的 `build_v2`、`glyphs`、`observe`、`freeze`、`terrain`、`storage`、`coverage`、`deduplicate`、`cli`）：(a) 也进对应数据集包的 `tools/` 子目录，一份数据的读与造都在一处；(b) 统一收进 `evals/datatools/`，数据集包只管读 |
| 已定 | world_script_execute 的用例格式 | 转成 `cases.jsonl`（常规与接管两类合并；接管用例在运行时的转换改为一次性转换后冻结）；`frames/capture_cases.py` 同样转成数据 |
| 已定 | 存档放几份 | evals 拷一份进 `evals/dataset/world_script_execute/v1/states/`；`experiment/` 保留自己那份不动 |

## 七、成功的样子

1. `python -m evals list` 列出的每个名字都能直接读出"哪个模块的哪个节点"。
2. 每个 task 只经 `evals/dataset/<task 或共用名>/` 的出口拿数据；冻结文件都在其下的 `<版本>/` 里且自包含；task 代码目录里不再有数据文件和读取代码，`evals/data/` 包不复存在。
3. `brain_choose_action` 跑完给出：可接受率、越权率、解析失败率，按场合与难点标签分组，每组带样本数。
4. `brain_goal_judge` 给出假阳率 / 假阴率与样本数，按难负例类别分组；e2e 里一次 judge 误判能追到它在数据集里的样本。
5. 两个数据集的每条样本都能只用冻结物复现（不重跑游戏）；改 prompt 后同一批样本可以直接重测对比。

## 八、不做

- verify、decompose / plan、reflect / summarize 的节点测评，memory 扩容，e2e 记忆对照与长程续跑（用户定）；
- `judge_interrupt` 链路；
- choose 的多步行为（连续多步是否走得通属于 `agent_goal_run`）；
- 改名之外动现有 task 的评分口径。
