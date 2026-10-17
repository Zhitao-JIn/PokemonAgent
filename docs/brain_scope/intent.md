# intent —— 大脑感知范围：三级目标，各层读同构的记忆

> 流程位置：**intent.md**（已确认）→ spec → plan → 落码
> 关联：`pokemon_agent/schemas/memory/datastore/{act,task,episode}_memory.py`、
> `pokemon_agent/schemas/harness/domain/goal_entry.py`、`pokemon_agent/direct/brain_tool.py`、
> `pokemon_agent/memory/recall.py`、`docs/ROADMAP.md`（E8）、`docs/perceive/remove-vision-spec.md`
> 本文只写最终意图；字段、函数、数值与实施顺序归 spec。

---

## 一、一句话意图

大脑的每一次调用，只读**它所服务的那个目标所绑定的单元**：详情是该单元下已产生的**全部**下一级子单元记忆，背景是同级过往单元的**一行索引**。三级目标各读一份同构的范围，**生成者与 judge 读同一份**。

## 二、为什么这样做

1. **同构。** 三层（run / episode / task）本来就是同一种结构的递归。范围也递归：一条规则，三处套用，不再是每个调用点各有一套特例。
2. **生成者与 judge 同范围。** judge 复核的正是生成者所依据的证据；两边看到不同的东西，复核就失去意义。
3. **详情取全部，规模由既有预算兜住，三层没有例外。** 现有的步数窗口（`CHOOSE_HISTORY_STEPS` / `JUDGE_HISTORY_STEPS`）是为了防长 task 撑爆 prompt；而三层本来就有预算上限：task 层 `min(Task.max_steps, task_max_steps)`、episode 层 `min(goal.max_steps, episode_max_tasks)`、run 层 `max_episodes`。run 层的 `max_episodes` 默认值 50 偏大，本项目把它降到 10，详情即可取全部，不再叠第二套旋钮。
4. **图跟着记忆走。** 读哪一级的记忆，就看那一级对应的 trace 帧；不为图另设来源。
5. **索引机械生成，不调模型。** 一行索引由记忆已有字段拼成；Task / Episode / Run 三级记忆的正文都已由 LLM 蒸馏过一次，索引只是它们的一行视图。
6. **run 级记忆必须有蒸馏正文。** 只有一串数字的 run 记忆，下一个 run 读到后看不出上一个 run 做了什么；所以它与 episode 级同构：来源章加一段从本 run 全部 EpisodeMemory 蒸馏出的正文。

## 三、三级目标与绑定

| 目标 | 是什么 | 绑定的单元 | 谁服务它 |
|---|---|---|---|
| level0 目标 | run 的总目标（`run_goal`） | run | `plan·L0` / `judge·L0` |
| level1 目标 | 目标表（goals 表）的一行，由 `plan·L0` 生成 | episode | `plan·L1` / `judge·L1` |
| level2 目标 | 一个 task 的目标，由 `plan·L1` 生成 | task | `plan·L2` / `judge·L2` |

上一级生成下一级：`plan·L0` 产出 level1 目标，`plan·L1` 产出 level2 目标（task），`plan·L2` 产出下一个动作。

## 四、可见范围

| 调用点 | 详情（全部） | 背景索引（一行一条，不含本单元） | 图 |
|---|---|---|---|
| `plan·L0`、`judge·L0` | 本 run 全部 EpisodeMemory | 过往的 run（run 级记忆，一个 run 一行；**不按 `run_goal` 限制**） | 每局首末帧 |
| `plan·L1`、`judge·L1` | 本 episode 全部 TaskMemory | 被同一个 `run_goal` 绑定的 episode（同一目标一次跑不完被重新发起时，它们会分布在多个 run 里） | 每个 task 首末帧 |
| `plan·L2`、`judge·L2` | 本 task 全部 ActMemory | 被同一个 level1 目标（目标表的那一行，由 `plan·L0` 产出）绑定的 task（含同一 level1 目标被重新发起的其他 episode 里的 task；不含本 task） | 每步前后帧 |

- **`run_goal` 只用来限制 episode 索引**（L1），不用来限制 L0 的 run 索引。
- 六处都另给**知识**与**当前 RAM 现状**。各调用点原有的、不属于「记忆」的输入照旧：goals 表（L0）、本 episode 的 task 表（L1）、动作空间与上一步结果（L2）、`last_judge`、`human_note`。

**命名**：`plan·L0` 即原来的 plan，`plan·L1` 即原来的 decompose，`plan·L2` 即原来的 choose；`judge·L0 / L1 / L2` 即三层 judge。本命名只用于文档，代码里的函数名不在本次改动范围。

## 五、规则细则

- **详情**：绑定单元下已产生的全部下一级子单元记忆，不设窗口，三层一视同仁。judge 与对应的 plan 同范围。
- **索引**：每条一行，机械拼出，不加结论，不含本单元自己。
  - episode / task 行：来源章（目标、成败、终止类别）加正文第一句；**成败只认章，不认正文**。
  - run 行：run 级记忆的来源章（`run_id`、`run_goal`、局数、成功局数、终止类别）加正文第一句；成败只认章。
- **图**：取自对应记忆里的 trace 帧，按帧去重；图片总数共用上限，超出从最旧的丢。
- **「过往」**：同级、更早产生、且不是本绑定单元自己的单元。

## 六、记忆侧改动（用户已授权，写通道仅限于此）

1. **EpisodeMemory** 加来源章 `run_goal`，以及可空的 `first_frame` / `last_frame`（PNG data URI）；首末帧由 harness 在盖来源章时取该局首个 task 的首帧与末个 task 的末帧，不调模型。
2. **新增 run 级记忆**：每个 run 收尾留一条，由 harness 盖来源章，正文由 LLM 从本 run 全部 EpisodeMemory 蒸馏（每条带成败标注，成败以目标表的最终定案为准，含人审推翻）。蒸馏失败或没有可蒸的 EpisodeMemory 时落一条只有来源章、正文为空的记录，保证每个正常收尾的 run 恰好一条（正常收尾含预算、时间、动作数耗尽等机械终止；异常上抛的 run 不写，从存档续跑到收尾时才写）。它补上记忆阶梯的最高一级（Act → Task → Episode → Run），它和 EpisodeMemory 一样是派生物：可重建、可丢弃，成败只认章。
3. **召回口**增加两种取法：按 `run_goal` 取 episode；列出 run 级记忆。L2 的背景索引不走召回：它取自 episode 层已装好的本 episode 全部 TaskMemory，按目标文本相同机械筛出，所以 TaskMemory 不加字段。
4. 旧记忆文件缺新字段时读作默认值，但不为旧数据写任何兼容逻辑；没有 `run_goal` 的旧 episode 在存档重打时随整库清空。
5. 既有的蒸馏 prompt 不动；新增一个 run 级蒸馏 prompt、一次模型调用，以及它的账（蒸馏调用、读 run 记忆、写 run 记忆三本，已与用户确认）。

## 七、预算

- `max_episodes` 默认值由 50 降为 10；评测对它的覆盖不变。
- 不设 L0 的条数上限（没有「最近 K 局」）。

## 八、明确不做

- 大脑三位 agent 化与工具式按需查询（ROADMAP E8，仍暂缓）。本项目定义的范围，将来就是 E8 里 agent 的默认上下文。
- 代码里函数、类的改名。
- 重新生成 level0 目标的机制（本项目只要求读取范围按「绑定」写，不因将来的重新生成而混读）。
- 既有蒸馏 prompt（task / episode）与既有 trace 落点的变化。
- 为了省 token 去折叠或改写记忆正文。

## 九、死代码清理（意图的一部分）

必须随改动同步清除，不留兼容壳：

- `CHOOSE_HISTORY_STEPS`、`JUDGE_HISTORY_STEPS` 及其全部读方、注释与测试。
- 因窗口而存在的截取、取最近 N 条的逻辑；run 层「最近 1 局加全部失败局」的详情预取规则。
- 被新范围取代的旧请求素材字段与对应渲染。

**范围判据**：只清「本次意图使之失效」与已核实的陈旧项；每项先查读方，读方清零才删；清理与引起它的那步同提交。历史记录（`CHANGELOG.md`、`changelog/`）不改。

## 十、需在 spec 阶段落实的前提

1. 召回口的具体取法：按 `run_goal` 取 episode 需要把它写进 episode 记录的可筛选元数据；run 级记忆的落盘位置与写入点（保证每个正常收尾的 run 恰好一条）；（原「全局 episode 条数上限 `max_summaries` 对 L1 索引的影响」已无需考虑：该上限与淘汰已由 CHANGELOG 478 删除，episode 记忆不再被淘汰。）
2. 评测存档：EpisodeMemory 与状态模型加字段会改变 `state_schema_hash`，存档要重打。
3. brain 的对外接口：`plan` / `decompose` 目前不收图，L0 / L1 带图要加 `images`。
4. 图片总数共用上限的数值。
5. 与 reviewer 的衔接：reviewer 的 `ReviewContext.brain_input` 原样带大脑请求；请求形状变了，`render_context` 须仍可用；其文档里「规划与拆解处不看图」一条需随之更正；两个项目的合并顺序与编号冲突在 plan 里写明。
6. 知识与 RAM 现状六处都给：run 层目前没有知识检索，judge 三处目前没有知识与观测，逐项落实。
7. 索引渲染函数的落点，遵循既有「渲染跟着数据形状放」。
8. run 级蒸馏的契约：新增的 brain 方法与请求信封、蒸馏 prompt、素材（EpisodeMemory 与成败标注、是否带图）、失败降级为空章、收尾位置与每个 run 恰好一条的保证、预算与超时。

## 十一、验收（机械可验）

1. 三个 `plan·Ln` 与对应 `judge·Ln` 读到的详情条数相同，均等于绑定单元下的全部子单元记忆。
2. 背景索引只来自第四节规定的范围，不含本单元自己；每条为单行文本。
3. episode / task / run 行对固定样例断言整行相等（样例正文固定，首句由确定性规则取）。
4. 索引生成过程零模型调用；run 级记忆的蒸馏发生在 run 收尾，每个 run 一次。
5. `CHOOSE_HISTORY_STEPS`、`JUDGE_HISTORY_STEPS` 在代码、测试与现行文档中零残留（历史记录除外）。
6. 图的帧来自对应记忆，按帧去重，总数不超过共用上限。
7. 缺新字段的旧记忆文件仍可读（读作默认值）；每个正常收尾的 run 恰好留一条 run 级记忆。
8. 全量测试与 ruff 通过。

## 十二、与既有设计的关系

- 本项目与 reviewer 项目**独立**：reviewer 读大脑请求原样，不依赖范围的具体定义。
- 它是 ROADMAP E8 的前置：先把「大脑看什么」定下来，E8 才谈「谁来取」。
- 取代 `CHOOSE_HISTORY_STEPS` / `JUDGE_HISTORY_STEPS` 的窗口语义；记忆阶梯在 Episode 之上多一级 Run。
