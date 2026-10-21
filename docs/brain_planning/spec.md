# spec —— 两层状态表规划与 judge 语义退出

> 状态：实现已落地；依据同目录 `intent.md`，验证结果见 CHANGELOG 561，采集状态见批次报告。
> 实施顺序见 `plan.md`。实际完成项与验证结果记录在 CHANGELOG 及批次报告。

## 1. 职责与边界

plan 维护 L0 下的 L1 goal 表，decompose 维护 L1 下的 L2 task 表。
两者负责新增、保留、重开、放弃和派发顺序，不决定父目标达成或无法推进。
judge 判断当前层目标；harness 负责采纳、派发、机械终止、执行结算和返回。
choose 仍只选合法动作，不增加停机动作、状态表操作或新的推理输出字段。

brain 无状态；请求和结果均由调用方提供或保存。Port 收裸字段；信封和两侧方言转换仍在 tool 层。
新增规划字段不得通过跨模块实现依赖共享；所有跨层结构使用 Pydantic 模型。

## 2. 两层规划请求

保留 plan/decompose 两个入口及各自请求信封，统一以下信息的含义：

| 信息 | plan | decompose |
|---|---|---|
| 父目标 | run_goal 的目标与验收条件，显式传入 | 当前 L1 goal 的目标与验收条件 |
| 子目标表 | 本 run 的 L1 goal 表 | 本 episode 的 L2 task 表 |
| 执行历史 | 表项尝试引用及本 run EpisodeMemory | 表项尝试引用及本 episode TaskMemory |
| 背景 | 过往 run 摘要 | 同 run、同 L1 goal 的其他 episode 摘要 |
| 现场 | 当前观测、既有世界事实与知识 | 当前观测、既有世界事实与知识 |
| 反馈 | 最新 judge/review 反馈 | 最新 judge/review 反馈 |
| 预算 | 新增数量、剩余规划轮数和可用执行预算 | 新增数量、剩余拆解轮数和可用执行预算 |

表行同时展示稳定身份、表内序号、目标、验收条件、预算、状态、尝试次数、最近执行引用、
修订理由与 review 定案信息。模型用本次快照的序号寻址，harness 翻译为稳定身份。
父目标不能靠子目标文本推测；目标验收条件与预算不能只藏在自然语言说明里。

## 3. 两层规划输出

RunPlan 与 Decomposition 保留独立类型，采用同构字段：

```json
{
  "new_items": [
    {
      "goal": "到达护士柜台前",
      "success_criteria": "玩家站在可与护士互动的位置并面向护士",
      "budget": {"limit": 6, "unit": "actions"}
    }
  ],
  "updates": [
    {"index": 0, "status": "abandoned", "note": "原站位目标不可达，改用新站位"}
  ],
  "execution_order": ["new:0", "existing:1", "existing:2"],
  "why": "先修正站位，再保留互动和确认治疗两个任务"
}
```

- `new_items`、`updates` 默认空列表；`why` 必填且非空，空规划也要说明理由。
- plan 的 `budget.unit` 固定 `tasks`，decompose 固定 `actions`；`limit` 为正整数。
  这里的 actions 沿用现有动作预算计数，不以模型调用数或帧数替代。
- `updates` 仅允许 `pending`、`abandoned`；模型不能直接写 completed/failed/blocked。
  重开或放弃必须有非空 note；重复指向同一行、越界和操作 RUNNING 都是不可采纳的输出。
- 未点名表项原样保留；更新不能就地修改目标、验收条件、预算或身份。
  实质变更通过放弃旧条目并新增替代条目表达，旧条目及其尝试历史保留。
- `execution_order` 可为 null，表示应用更新后保留原 pending 顺序，再追加新条目。
  显式给出时必须恰好列出应用后所有 pending 条目一次，不能重复、缺失或引用其他状态。
  `existing:n` 指请求中的第 n 行，`new:n` 指本次第 n 个新增；不让模型编造 ID。
- 状态表行顺序保持稳定；派发顺序单独保存为稳定身份列表，避免排序导致历史序号含义变化。
  本阶段不新增依赖 DAG；模型通过完整执行顺序安排前置任务，质量评分检查合理性。
- 新增为空不表示没有 pending，也不表示无法推进。不设 proposal/blocked 输出分类或请求复判标志。

空规划的有效例子：

```json
{"new_items": [], "updates": [], "execution_order": null, "why": "剩余任务仍适用，按原顺序执行"}
```

## 4. 原子采纳与状态表权限

采纳顺序为：解析 → 按请求快照验证操作与预算单位 → 既有 review → 验证最终版本 → 原子应用。
任何非法操作都拒绝整版，不再静默丢弃越界更新；按既有 tool 重试与显式失败链记录。
校验依赖请求上下文的部分归 tool/harness，brain 仍只认识自己的结构和裸字段。
重试前不得部分更新状态表、分配正式条目身份或消耗执行次数。

| 状态变化 | 权限与条件 |
|---|---|
| pending → running | harness 派发时，且全表没有其他 running |
| running → completed/failed/blocked | harness 从对应执行输出结算，并保留 review 定案 |
| failed/blocked/abandoned → pending | 规划器显式重开，有理由，经过既有 review 采纳 |
| completed → pending | 有明确重做依据，经过既有 review 采纳，旧成功记录保留 |
| pending → abandoned | 规划器显式放弃，有理由 |
| 未被点名 | 原状态及历史保留 |

新增 `EntryStatus.BLOCKED` 表示最近一次执行被 judge 判定无法推进，不能自动计成失败或放弃。
已有 task 失败后不再自动 abandoned 全部剩余 pending；decompose 读取结算后自行修订。
原表项的定案历史保留在各次执行账中；重开后的当前状态不抹去历史结论。

## 5. 逻辑目标与执行身份

L1 沿用逻辑 goal 身份与 episode_id 分离；L2 引入独立 `entry_id` 与执行 `task_id`。
TaskEntry 的目标内容是逻辑条目定义，派发时复制为具有本次 task_id 的 Task。
执行 ID 由 harness 使用 episode_id 和单调递增派发序号生成，重开不能复用旧 task_id。

两层表项均保存 attempts 和最近一次执行引用；L1 引用 episode_id，L2 引用 task_id。
L2 TaskInput/TaskOutput 加入逻辑 entry_id，TaskMemory 来源章保存逻辑引用与执行 task_id。
结算同时核对父执行、逻辑条目和子执行身份，不能按目标文本或最新一条同名记忆猜测。
全部尝试可从 episode_outputs/task_outputs、记忆来源章及 trace 回查。

预算按每次执行和父层累计量分别计数：重开可获得该条目规定的单次预算，
但不返还已消耗的动作、task/episode 次数、时间或规划轮数。新执行不能重置父层预算。

brain scope 保持既定口径：

- L0：本 run 的全部 EpisodeMemory；过往其他 run 的 RunMemory 仅作背景。
- L1：本 episode 的全部 TaskMemory；同 `(run_id, L1 goal_id)` 的其他 episode 作背景。
- L2：本 task 执行的全部 ActMemory；同 episode 内同 task 目标文本的其他 task 作背景。
- 新 entry_id 用于结算和追踪，不顺带把 L2 背景改成按 entry_id 检索，也不扩大跨 run 范围。

## 6. judge 契约与收尾

judge 的模型输出统一为 `decision` 与非空 `why`，不同时存多个可冲突的布尔位。
`decision` 允许 achieved、continue、blocked；task 层另保留 interrupted。
done/success 等兼容读法从 decision 或 termination 派生，不能另存一份。

| decision | 条件 | 终止结果 |
|---|---|---|
| achieved | 本层验收条件有执行或现场证据支持 | GOAL_DONE，success 为真 |
| continue | 当前层允许的行动仍可合理推进 | 不终止 |
| blocked | 有具体阻塞依据，当前层无法解决，需上层调整 | 新增 BLOCKED，success 为假 |
| interrupted | 仅 task：既有意外场景打断语义 | 保留 INTERRUPTED |

blocked 不是“这次未成功”“不保证成功”“没想到方案”或“表为空”的同义词。
why 应交代阻塞条件、证据及为何需上层调整；judge 可以在仍有 pending 时判 blocked，
因为待办存在不代表待办可行。judge 不能代替规划器新增或改写任务。

judge 请求补充本层子目标表；无待办复判时还携带最新采纳规划、规划轮号与触发原因。
这些属于判断素材，不能当成已发生的执行证据。task 层无规划表时保持为空。
新规划理由在 prompt 中单独标成主张；不能混入记忆来源章充当事实。

achieved/blocked 的 review 使用统一决策展示，保留原各层启用策略；
接受才采用对应语义结论，推翻则反馈给后续规划，不能将“接受 blocked”误映射成 GOAL_DONE。
task interrupted 保留原打断处理，不因本次改动新增必须等待的审点。
预算闸门已决定机械停止时不为复判额外调用模型；异常处理保留既有职责。

task_done → TaskOutput → episode、episode_done → EpisodeOutput → run 的返回通道复用。
run blocked 经 run_done 返回外部调用方；没有更高一层规划器。
零动作/零 task 的收尾不编造蒸馏输入，沿用空章或机械来源章，保留 judge_reason。

父层结算：achieved 记 completed；blocked 记 blocked；interrupted 保持既有失败标记及说明；
其他结果按既有非成功规则处理。blocked 与 interrupted 不增加、不清零连续失败计数；
成功清零，普通失败继续按既有规则累计。所有派发均占次数，避免反复 blocked 绕过预算。

## 7. 图路由、规划时机与有界性

run/episode 都在入口感知与正常 judge 后规划；每次子执行结算后，若本层继续，
都再次调用本层规划器，包括仍有 pending 的情况。移除 decompose 的 pending 直通。
正常 judge 保留入口零执行时跳过模型的现有策略；无待办复判即使零执行也必须可调用。

```text
perceive → review_and_judge
  终止 → *_done → 返回
  继续 → plan_run / plan_episode
    机械终止 → *_done
    有 pending → act → perceive
    无 pending → review_and_judge（无待办复判）
      终止 → *_done
      继续 → plan_run / plan_episode
```

无待办复判直接使用刚才的观测、已结算表与最新规划，不再次 perceive 或重复吸收子执行。
使用可序列化的 judge 触发原因区分正常循环与无待办复判，不新增存第二份结算结果。
反馈继续时携带给规划器；同一无待办分支不重复结算 running，也不累加执行次数。

episode 每次实际拆解均消耗已有 max_decompositions，包括空规划和 review 重写；
tool 内格式重试只消耗模型尝试预算。run 新增独立 max_planning_rounds 及已用计数，
配置集中于 RunBudget/config，采集与 checkpoint 显式记录。
达到轮数上限机械终止为 PLANNING_EXHAUSTED（run）或 DECOMPOSITIONS_EXHAUSTED（episode），
不伪称 judge 判了 blocked。
生产默认 max_planning_rounds 为 20，max_decompositions 从 2 调整为 12，
分别按现有最多 10 个 episode、6 个 task 的两倍提供有限规划余量。
本轮二十场景显式配置 max_planning_rounds=6、max_decompositions=12，
保留 max_episodes=3、max_total_actions=60 和 wall_clock_s=600。
review 重写也会消耗这些额度，因此余量不保证每次可用尝试数，耗尽仍机械停止。
预算变更必须进入新配置及 manifest，旧批次与新批次不宣称是相同规划预算下的直接对照。
LangGraph 承载全部重规划和复判循环，不在节点内部手写循环。

## 8. trace、review 与恢复

规划调用账保留每次模型尝试；采纳账保存新增、更新、顺序、理由、版次及原请求快照关联。
空规划也有采纳账。派发账关联 entry_id、执行 ID 和尝试次数；结算账记录原终止类别。
judge 调用及定案账保存 decision、触发原因、对应规划版次与 review 反馈。
仍使用现有六字段 trace 封套和六件 meta，不把新字段塞进 meta 扩展维度。

RunState/EpisodeRunState 增加规划计数、最新采纳规划、派发顺序及复判触发信息；
TaskEntry、执行交界和记忆来源章同步升级。恢复后不重置计数、不重复派发或重用执行 ID。
新 state_schema_hash 与旧存档不兼容时按现有规则拒载，不能只修改 hash 强行加载。
本轮从原始模拟器 .state 重打二十个 run 起点，原始 .state 内容和哈希保持不变。
新起点放独立批次目录，采集器显式选择该目录；旧冻结 archives 不覆盖。

## 9. 评测与数据版本

四个独立公开任务仍由 Inspect AI 管理，summary 继续保留原料。
solver 离线调用生产 Port，不起模拟器、不执行候选方案；生成只接收请求素材。
AI 质量评分读取 solver 实际使用的 prompt/图片、候选与独立参考，不能获得额外未来结果。
参考仍是建议式、多解；空新增不是自动零分或自动满分。

plan/decompose 结构评分增加原子更新、单位、身份引用和执行顺序合法性；
质量评分覆盖验收条件、历史使用、前置顺序、保留/重开/放弃与空规划理由。
judge 新版本用独立历史标注评 decision 混淆矩阵与逐类准确情况；无法推进依据由
独立 AI 按建议式证据参考另列质量分，不混入分类准确率。旧真假准确率只能评价
achieved 与非 achieved 的投影，不能代替 blocked/continue 标注。
choose 结构与动作契约不变；其现场会因新规划改变，需要收集新请求。

旧请求仅在证据完整时适配新字段，保存原指针及哈希；不能为旧请求猜补父目标验收条件、
历史尝试或规划复判素材。旧 judge 的 false 不得直接变成 continue，需重新审阅。
冻结 brain_calls v1、旧独立任务版本、标注与日志不修改；新原料发布 brain_calls v2，
四族分别发布后续版本并记录来源与 schema 指纹，原始响应不能直接作为评分真值。

本轮重跑二十场景，录全 judge、plan、decompose、choose、summary，保留 verify/reflect 旁证。
自然运行未覆盖的空规划、已有 pending 时调整、重开、blocked 等路径明确列覆盖缺口；
必要时另建来源可追踪的定向现场或合成测试，不能冒称二十例自然覆盖所有分支。

## 10. 脚本控制采集

扩展现有 capture_batch/capture_case，不用人工实时查看日志来决定下一步。
新增控制入口负责 preflight → pack → capture → audit → export，阶段结果原子落盘。
命令接口在实现时提供 start/status/stop/resume；status 只读状态与报告，不轮询 UI 或终端。

控制器必须：

1. 固定已提交代码、生产 prompt、schema、配置、模型、二十样本与来源哈希，变更则中止。
2. 使用专用 world/memory 服务，串行执行；新批次、存档、日志、记忆相互隔离。
3. 每次 Port 请求先落盘，再记录响应或显式失败与结束时刻；超时保留 pending，不伪造完成。
4. 分开记录 Port 耗时、模型尝试耗时和 reviewer 等待（judge 审、plan/decompose 插话及重写）。
   reviewer 的 wait_s、来源、轮次与询问/答复标识从生产 trace 保留；未询问记 not_requested，
   询问未结束记 pending，不能把 missing 或 Port 总耗时填成 reviewer 等待。
5. 每例结束自动双向核对录制与 trace，列各层每口数量、失败、pending 和等待覆盖。
6. 业务失败作为真实现场保留；基础设施异常、录制缺口或版本漂移阻止正常发布。
7. stop 先停止派下一例并允许当前例在既定超时内结束；强制停止显式标 interrupted。
   resume 跳过已审计完成例，未完成例以新 attempt 目录重跑，不能覆盖原证据。
8. 仅在批次完整性审计通过后导出新原料；标签审阅和评测发布有单独状态，采集完成不等于评测已完成。

## 11. 验收条件

- 两层规划输出同构，验收条件与预算单位明确，空新增可解析且不触发格式重试。
- 已有 pending 仍能修订；失败不自动清空剩余计划；前置任务可排在保留任务之前。
- 同一逻辑 L2 条目重开产生独立执行，旧记忆、trace、预算与 checkpoint 不被覆盖。
- 无待办复判看得到本次规划；判 continue 可重规划，判 blocked 经既有收尾上返。
- pending 存在但不可行时，正常 judge 仍可判 blocked；所有复判循环均有预算上限。
- review 接受 blocked 不会标成功，父表状态和失败计数符合本规范。
- 不改变已确认 brain scope；四族 solver 与评分现场一致，无未来信息或参考泄漏。
- 二十原始 .state 哈希不变，新起点和新采集批次可追溯，旧冻结数据不改写。
- 采集控制器自动留阶段报告、调用对账和各类等待；不依赖人工实时监控。
