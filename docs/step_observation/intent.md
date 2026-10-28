# intent —— 按步观察取代事件：脚本内逐键观察，摘要与索引重构

> 流程位置：**intent.md**（待确认）→ spec → plan → 落码
> 关联：`docs/script_dialog/intent.md`（本项取代其 `dialog` 字段）、`docs/eval/mid_tasks/intent.md`（M1、M4 依赖本项）、`docs/eval/metrics/intent.md`、`docs/brain_scope/intent.md`
> 状态：已确认（2026-10-27；第五节四点按设计侧倾向取默认，用户确认"给出交接"）。

---

## 一、一句话意图

不再单独存"事件"：脚本内每按一键也产出一份观察，和按键路径同一个形状；摘要的事实块从观察序列里机械摘出并全部保留；摘要的索引与解读由 LLM 在同一次调用里一并产出；对象记忆整体删除。

## 二、为什么

1. 现状里脚本只有首尾两份观察，中间过程只剩一行结局码（`result_line` 读错位置，真实链路里连摘要和原因都丢了），对话文字靠 `dialog` 字段补，自动过场（进店领包裹）没有物体被撞到，连事件都没有。
2. "事件"散在五处各有各的形状：world 的物体交互事件、对象记忆、`ActMemory.result`、`ActMemory.dialog`、脚本终态报告的 `code` / `summary` / `reason`。
3. 观察里其实已经有了事件所需的一切：对话是屏幕文字变了，进门是 `map_id` 变了，状态变化是钱、背包、队伍变了。唯一缺的是脚本内部每一键，以及钱、背包、队伍不在观察里（它们只在 trace 的 `RamReadout` 里）。
4. 摘要里的关键证据（收件人、顾客台词、哪一步进了背包）现在全靠 LLM 决定留不留，没有固定位置；一行索引又是从摘要开头截的。

## 三、做什么

1. **观察分两档，同一形状。**
   - 完整观察（决策边界的前后各一份，沿用现有 `Observation`）：新增 `ram`（钱、背包、队伍的种类 / 等级 / HP / 状态、`in_battle`）与 `facing_object`（面朝物体的种类和格子，没有则空）。
   - 紧凑观察（脚本内每一键一份）：`step`、`place`、`facing`、`scene`、`overlay`、`dialog_text`、`options`、`cursor`、`screen`、`ram`、`facing_object`，战斗中另带 `battle_status`；不带 `landmarks`、`cells`、`neighbor_cells`、`terrain_visible`、`option_grid`、`cursor_cell`、`option_annotations`。
   - 删除死字段与旧字段：`overview`（已无人赋值）、`perceived`、`observation_flags`。
2. **world 在脚本每一键、按现有稳定判定（连续 6 次轮询相同，约 24 帧）之后读一份紧凑观察**，脚本终态报告顶层新增 `observations`（按序列表），取代 `events[]` 与 `dialog`。按键路径不变（每键本来就是一次完整观察，只需带上 `ram` 与 `facing_object`）。不加强制等待。
3. **`ActMemory` 携带观察序列与结构化的脚本结局**：新增 `observations` 与 `outcome`（`code`、`ok`、`summary`、`reason`，取自终态报告顶层，键动作为空），去掉 `result`（拼好的一行字符串）与 `dialog`；`result_line`、`describe_call`、`last_event`、`last_result` 退役，"上一步发生了什么"由 `outcome` 与观察序列的差异在提示词模块里渲染。脚本结局码不是观察差异能推出的（如 `not_enough_money`），所以保留成结构化字段。
4. **对象记忆整体删除**：`object_memory` 一族、`store_object_semantic_memory`、`retrieve_object_semantic_memory`、`read_plan_context` 里的对象读取、`object_events` 提示词片段、world 里的"撞到什么就产出什么"判定（只保留"面朝物体"那一小块）。
5. **摘要分三块，task、episode、run 同形**：
   - 来源章：harness 机械盖章（同现在）。
   - 事实块：机械，从观察序列里按"相邻两条哪些字段变了"摘出对话行、进门、钱 / 背包 / 队伍变化、结局，带对象、地点、步号；**先全部保留，不截断**。差异规则写成一个纯函数并有测试。
   - 解读：LLM，沿用 `reason`、`reusable_patterns`、`critical_decisions`、`failure_points`。
   - 下钻指针：子记录编号或步号区间，机械填。
6. **索引由 LLM 与解读在同一次调用里产出**，存成字段：`headline`（一句话：做了什么加结果）、`keys`（可检索关键词：对象名、地点、物品、人名）、`evidence`（含哪几类证据）。渲染时拼成一行，成败与编号取自来源章。两条机械检查：`keys` 每项必须在事实块或观察里字面出现；`headline` 的成败必须与来源章一致；不过就重试。
7. 背景索引的读取方式这次不变（一次取全部、渲染成行）；以后改成渐进展开的检索 agent，读取点集中在 `dispatch_task`、`retrieve_episode_index`、`_read_run_index` 三处。

## 四、不做

- 不改等待与稳定判定（24 帧），不逐帧读屏，不加 `▼` 规则；稳定性实测另行进行（`experiment/probe_settle.py`），结果出来再决定是否收紧。
- 不做渐进展开的检索 agent，不改预算语义（`max_steps` 仍数决策次数，观察条数单独统计）。
- 不改机械判据本身；读 `write_object_memory` 事件的评分规则要迁移成读观察序列，迁移另案列出。
- 不做摘取上限与折叠（先全留），上线后看实测 token 再定。

## 五、已定

1. 索引结构：`headline` 加 `keys` 加 `evidence`。
2. 观察里加 `settled` 布尔：稳定判定超时才记 `false`，下游遇到 `false` 不把那条文字当证据。
3. 预算语义保持"一个决策一步"，观察条数单独统计。
4. 紧凑观察每键完整写 `ram`，先全留，实测后再折叠。

## 六、影响面与风险

- 影响面：`world`（脚本读取、终态报告、判定层缩小）、`harness`（`act`、记忆写入、`last_result`、`detect_stall`、摘要三个节点、检索）、`schemas/memory`（`ActMemory`、三个摘要模型）、提示词（`memory_records`、`decide_action`、三个摘要任务各出新版本）、评分器（`write_object_memory` 相关规则）、数据集样本里读事件的判据、`EpisodeMemory` 与 `RunMemory` 与 `TaskMemory`。
- 取代 665–666 的 `dialog` 字段与 `memory_records` v3。
- 风险：记忆体量上涨（脚本一次几十份紧凑观察、事实块全留）会进提示词，缓存只能扛一部分；读侧（评分器、reviewer、trace 回放、蒸馏）对 `act_call` 与 `ActMemory` 的字段假设需要逐个核对；提示词变了会让缓存前缀与评测结果都变，需先小集对比。

## 七、成功的样子

- 对一次进店领包裹的脚本调用，`observations` 里能依次读到进门、对话各行、背包里多出包裹；`ActMemory` 里同样存在，且没有 `result`、`dialog`。
- 一个 task 的摘要事实块包含这些对话行与背包变化，索引的 `keys` 含收件人与物品名，机械检查通过。
- 全仓没有 `object_memory`、`events[]`、`result_line`；评分器迁移后现有短期样本的判据结论不变。
