# intent —— 测评分三类：tests（pytest）、evals·DeepEval（无轨迹）、evals·Inspect（有轨迹）

> 流程位置：**intent.md**（本文）→ spec.md → plan.md → PR → production
> 状态：第一阶段（decode 迁到 B 类）**已完成**（提交 430–434，见第八节）；第二阶段（其余五个 task 迁完）**已按用户授权实施**（见第十节），spec 见 `eval-split-spec-2.md`。
> 起草：2026-10-12（v2：补上 pytest 类；v3：decode 改归 B 类；v5：B 类改为 DeepEval `evaluate()` 启动、自写逐字段指标、DeepEval 原生汇总，不再用 pytest；v6：未标注字段不参与统计、空值照常计分；evals 按任务名分目录；v7：补第二阶段，其余五个 task 全部迁入任务目录）
> 关联：`docs/eval/eval-split-spec.md`（第一阶段）、`docs/eval/eval-split-spec-2.md`（第二阶段）、`docs/spec/evals/SPEC.md`、`docs/eval/tasks-intent.md`

---

## 一、一句话意图

按三个问题把所有测试归类：**是不是纯代码正确性**（→ `tests/`，pytest）；**是不是 agent 直接相关**（→ `evals/`）；**agent 相关的任务有没有轨迹**（有 → Inspect，无 → DeepEval）。

## 二、为什么这样分

1. **pytest 不是 evals 的一类。** 单元、功能、集成测试检验的是代码是否正确，不涉及 agent 决策，不属于评测，放在 `tests/`。
2. **评测只看 agent 直接相关的部分。** 动作空间、RAG 召回、视觉读取、脚本执行、大脑决策，都是 agent 的能力，放在 `evals/`。
3. **有轨迹与无轨迹的运行方式不同。** 有轨迹的任务是多步、有时间序的 agent 行为，需要 Inspect 的 transcript、epochs 与 Langfuse 对应。无轨迹的任务是单次输入、单次输出，由 DeepEval 的 `evaluate()` 启动：一个状态一个测试用例，真值比较逐字段，统计由 DeepEval 按指标汇总输出。

## 三、三类的划分判据

| 类 | 位置 | 判据 | 运行 | 指标来源 | 调 LLM |
|---|---|---|---|---|---|
| **A. 代码测试** | `tests/` | 验证代码正确性（单元、功能、集成），不涉及 agent 决策 | pytest | 断言 | 否 |
| **B. 无轨迹评测** | `evals/<任务名>/`，入口 `__main__.py` | agent 直接相关，单次输入输出，无多步轨迹 | DeepEval `evaluate()` | 自写的逐字段确定性指标；需要语义判断时用 DeepEval 默认指标（如 GEval） | 视用例而定 |
| **C. 有轨迹评测** | `evals/<任务名>/`，入口 `task.py` | agent 直接相关，多步、有时间序的行为 | Inspect task | Inspect scorer；轨迹解析指标自写 | **必然调用** |

判据顺序：先问是否为代码正确性（是 → A）；再问是否 agent 直接相关（否 → A）；最后问是否有轨迹（有 → C，无 → B）。

**B 类的运行方式：** 一个 B 类 task 是一次 `evaluate()` 调用。每个状态（一帧、一个用例、一次查询）对应一个 `LLMTestCase`；真值比较逐字段进行，每个字段一个指标。没有标注的字段不挂指标，不进统计（值为空的字段算已标注，照常计分）；全部跑完后由 DeepEval 输出整体通过率和按指标（即按字段）的汇总表。B 类不使用 pytest。

**目录规则（v6）：** `evals/` 下直接以任务名作目录，该任务自己的 dataset、solver、scorer 等放进同一目录，不再分散在 `evals/dataset/`、`evals/solvers/`、`evals/scorers/`、`evals/tasks/`。这取代 `docs/eval/tasks-spec.md` §1.4 的槽位规则。第一阶段只迁了 decode；其余任务在第二阶段迁入（第十节）。多个任务共用的东西不属于任何一个任务，放 `evals/common/`；共用的数据集（如帧数据集）仍留在 `evals/dataset/`。

**边界规则：**

- 三类互不包含。一个任务只归属一类。
- 归类看被测对象和形态，不看是否用了模型。`episode_vision_read`（已删除（2026-10-16，见 docs/perceive/remove-vision-spec.md）） 用了视觉模型，但输入是单帧截图，属于 B。`decode` 不调 LLM，但它是 agent 感知链路的一环，在冻结帧数据集上有成功率指标，同样属于 B。
- C 类一律有 LLM 参与。纯状态比对且无 LLM 的检查，不进 C。

## 四、任务归属

| 任务 | 类 | 理由 |
|---|---|---|
| decode | B | agent 感知链路的机械解码；单帧输入，在冻结帧数据集上有成功率指标；不调 LLM，用自写的逐字段确定性指标 |
| world_script_execute | B | 单次脚本调用，结果与世界真值比对，无 agent 轨迹 |
| memory_store_recall | B | RAG 检索，单次查询 |
| episode_vision_read（已删除（2026-10-16，见 docs/perceive/remove-vision-spec.md）） | B | 视觉工具，单帧输入 |
| memory_poisoning_resistance（提议） | B | 单次记忆写入判定 |
| script_interrupt_recovery（提议） | B | 单次脚本执行的中断处理（需先核对是否已被 106 例覆盖） |
| brain_choose（S4） | B | 动作空间内的单步选择，即"action space"任务；设计见 `brain-choose-intent.md` 与 `brain-choose-spec.md` |
| brain_step_verify | B | 单步前后观测判断 |
| brain_reflect_replan | B | 注入单个失败情境后的反思 |
| brain_plan_decompose | B | 单个目标的任务分解 |
| brain_judge | C | 输入含观测历史，属于多步轨迹 |
| agent_short_goal_run | C | 完整系统多步执行 |
| agent_long_goal_run | C | 多里程碑长程执行；里程碑检查在此 task 内完成 |
| agent_stall_recovery_run | C | 多步脱困过程 |
| agent_memory_ablation_run | C | 成对的多步运行比较 |

## 五、横切要求

这些要求适用于多个任务，不单独成 task。

- **模型判定的人工校准。** 凡用模型做判定的任务（B 类中的 GEval 判定、C 类中的 model-graded、视觉读取），都要用人工标注做一致率校准。这取代了原先的 `judge_calibration` 任务。换评审模型（deepseek → qwen3.8）时，校准结果是必需的对照依据。
- **评审模型配置统一。** 两类都从 `evals/config.json` 读取，缺键即报错，沿用现有 runconfig 约定。当前为 deepseek，目标为 qwen3.8，切换只改配置。
- **C 类可以复用 DeepEval 指标，但推荐自写。** 允许复用，但 C 类的主要工作是轨迹解析，指标应围绕轨迹自己写。
- **里程碑检查归 C 类。** `agent_long_goal_run` 的里程碑达成判定是该 task 的 scorer 的一部分，不单独拆出。
- **未标注字段不参与统计；空值算已标注。** 真值里没有该键，才不挂指标；真值为 `None`、`""`、`[]` 时照常比较，decoder 本应为空却输出内容仍算失败。
- **判定语义不变，统计口径有意调整。** decode 的逐键比较规则不变（`screen_contains` 逐条核对；真值为 `None` 仍要求实际输出该键）。统计由原先的四组 `C/(C+I)` 改为：逐字段通过率与计分数、帧级通过率，均由 DeepEval 汇总。
- **被测系统代码不动。** 本次只动 `evals/`、`tests/`、`scripts/` 与文档。

## 六、"两侧"的含义

"两侧"指 **B 类（DeepEval）与 C 类（Inspect）**，即 `evals/` 下的两种运行形态。A 类（pytest）不属于两侧，它在 `tests/` 中，与评测分开。

## 七、已确认

1. brain_step_verify、brain_reflect_replan、brain_plan_decompose 归 B 类（单步判断）。
2. brain_judge 归 C 类（输入含观测历史）。
3. world_script_execute 归 B 类（单次脚本调用，脚本内部按键不算 agent 轨迹）。
4. 评审模型两类共用 `evals/config.json`。
5. B 类不绑定 pytest，真值比较自写逐字段判断，汇总由 DeepEval 输出。
6. `scripts/decoder_baseline.py` 去掉，其逐字段统计由 DeepEval 的汇总取代。
7. 未标注字段不参与统计，空值算已标注。
8. `evals/` 按任务名分目录，任务自己的 dataset、solver、scorer 放进该目录。

DeepEval 的接法已在隔离环境（Python 3.12，deepeval 4.2.8）验证，结论与实现细节见 spec。

## 八、第一步：decode 迁到 B 类

**做什么：**
- 新建 `evals/decode/`，含自己的 dataset、solver、scorer。
- 由 DeepEval `evaluate()` 启动：每帧一个 `LLMTestCase`，每个真值字段一个自写指标（共 23 个）；仅未标注不挂指标。
- 输出 DeepEval 的整体通过率与按字段汇总表，只显示失败的帧。
- 从 `registry.py` 移除 decode，公开 Inspect task 变为五个；删除旧的 decode 代码与 `scripts/decoder_baseline.py`。
- 同步文档中对旧 decode task 与基线脚本的引用。

**不做什么：**
- 不改解码逻辑、真值、帧集（`frames/v2`）。
- 不启动模拟器（decode 已经不启动，保持）。
- 不迁移其他任务，不移动 `evals/dataset/frames/`。

**验收（意图层面）：**
- 迁移前后，同一份帧集上每个 (帧, 字段) 的判定结果逐项一致。
- 用一条命令得到整体通过率与逐字段汇总表。
- `python -m evals list` 不再列出 decode。

## 九、非目标

- 不引入 DeepEval 替代 Inspect，也不把 Inspect task 改写成 B 类。
- 不在本次拆分中新增任务。补充任务（memory_poisoning_resistance、script_interrupt_recovery，以及 brain_choose 等 B 类提议任务）待单独排期。
- 不改变 Langfuse 的 run_id 对应关系。
- 不改判定语义、数据集、真值与被测代码。

## 十、第二阶段：其余五个 task 迁完

**做什么：**
- **B 类三个**改为 DeepEval 入口，口径沿用 decode（一个状态一个用例、确定性自写指标、无从判不进分母、DeepEval 原生汇总）：
  - `memory_store_recall`：逐记录判存储，逐查询给 recall@k 与 MRR；
  - `world_script_execute`：106 条用例，判"自报"与"真值"两面，另按脚本给通过率；
  - `episode_vision_read`（已删除（2026-10-16，见 docs/perceive/remove-vision-spec.md））：视觉模型读单帧，五个视觉字段加"解析成功"共六列，对照人工标注。
- **C 类两个**（`brain_judge`、`agent_short_goal_run`）仍是 Inspect task，只把代码搬进各自的任务目录，逻辑不变。
- 迁完后 `evals/solvers/`、`evals/scorers/`、`evals/tasks/` 不再存在，`evals/dataset/` 只留共用数据集；公开任务共六个：四个 B（含 decode）、两个 C，登记在 `evals/registry.py`。
- decode 的 DeepEval 运行器抽成公共的 `evals/common/run.py`，四个 B 类共用。

**为什么这样做：** 第一阶段已验证 B 类的结构可行；剩下的任务按同一判据归类后，继续散在四个按"角色"划分的目录里，会让"一个任务的东西"仍然要跨目录找。

**不做什么：**
- 不改判定语义、数据集、真值和被测系统代码。
- 不新增任务，不引入需要 LLM 判分的指标（三个 B 类全是确定性判定）。
- 不改 C 类的 scorer 与 solver 逻辑。

**需要你确认的取舍**（详见 spec-2 第〇节 D1–D9）：
1. `world_script_execute` 的"按脚本分组准确率"改为每个脚本一个指标 `pass.<脚本名>`（38 个），原按 `kind` 的分组不再单列。
2. `episode_vision_read`（已删除（2026-10-16，见 docs/perceive/remove-vision-spec.md）） 正常调视觉模型；调用本身不通的帧不进分母，运行时打印提示。迁移前后的等价性靠保存基线时的模型输出对照，不重复调模型。
3. 共用数据集留在 `evals/dataset/`（已按你的意见，不再改名）。
4. 开工前需要你先提交当前工作区约 125 项未提交改动（`agent_goal_run` → `agent_short_goal_run` 改名及 CLI 删除），否则 C 类的目录迁移会与未跟踪文件混在一起。

**验收（意图层面）：**
- 三个 B 类任务迁移前后，同一份数据上每个 (用例, 指标) 的判定逐项一致。
- 一条命令得到整体通过率与逐指标汇总，有失败时退出码非零。
- 六个公开任务都能从 `evals/registry.py` 找到入口；`evals/solvers/`、`evals/scorers/`、`evals/tasks/` 不存在。
