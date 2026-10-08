# spec —— world_script_execute 与 agent_goal_run 的下一版

> 流程位置：（本轮没有 intent，范围由用户 1008 定：**只做这两个 task**）→ **world-e2e-spec.md** → world-e2e-plan.md
> 现状以 2026-10-08 仓库为准（CHANGELOG 424）。用户已确认收敛为 **31 个公开脚本**；本次只更新规格与计划，能力收敛尚未实施。decode / episode_vision_read / memory_store_recall / brain_goal_judge 本轮不动。

---

## 〇、暂定项（按推荐写入，可推翻）

| 编号 | 暂定方案 | 备选 | 影响小节 |
|---|---|---|---|
| W1 | world 补用例出 **v2**，v1 冻结不动 | 直接追加进 v1 | §2.3 |
| W2 | `switch_from_party_list` 按 **world 缺陷**修，期望不改 | 登记为已知失败继续带着 | §2.4 |
| W3 | 用例加 `kind`（success / failure / interrupt）字段；v1 读取时由 `expect.ok` 推出 | 不分类 | §2.3、§2.6 |
| E1 | 判据类型（event / final）**登记在规则上**（`@rule(id, mode=…)`），不写进样本，v1 数据零改动 | 写进样本字段 | §3.3 |
| E2 | 样本可解性用**脚本化大脑**（实现 `BrainPort`、经装配点注入）跑真 harness 校验 | 只在 world 层验可达，不验判据 | §3.4 |
| E3 | 结果评分模型换成**与被测系统不同的型号**（具体型号待用户定） | 继续用 deepseek-flash | §3.6 |
| E4 | v2 规模：L1 20（v1 原样）+ L2 ≈10 + L3 ≈5；L3 进 `test` 切分 | 只做 L1 + L2 | §3.5 |
| E5 | 正式基线 **k=3**；记忆开关对照作为可选的最后一步 | k=1；或不做对照 | §3.6、§3.8 |
| E6 | v2 样本 schema 删 `rubric` / `k_metric`（零消费者），v1 loader 兼容读 | 保留 | §3.2 P5 |

**world 已确认的架构约束**：只暴露 §2.1 的 31 个完整操作；内部脚本由 world 实现和调用，
不出现在动作空间、模型签名、MCP 工具列表或外部通用分发中。常规/接管只描述内部实现，
不作为公开能力分类。W1/W2 已完成；新增能力目录与合并工作必须先于 v2 用例冻结。

---

## 一、两个 task 的定位与关系

| | world_script_execute | agent_goal_run |
|---|---|---|
| 测什么 | 一次脚本调用，在真模拟器上有没有做到它报告的事 | 给一个目标，整个系统能不能完成 |
| 被测对象 | world 的公开脚本契约（目标为 31 个）；内部步骤由 world 自行组合 | brain + harness + memory + world 全链路 |
| 模型 | 无 | 被测系统五个模型位 + 结果评分模型 |
| 确定性 | 确定（冻结存档 + 固定按键） | 不确定，要多 epoch |
| 单例成本 | 秒级、零费用 | 分钟级、有 API 费用 |

**关系**：agent 的每次 `act_call` 走的就是同一套脚本。所以 world 的结论是 agent 的**下界**——脚本坏了，agent 无论大脑多好都会失败。agent 的失败要先排除"脚本坏"再归因到大脑（§3.7）。world 的覆盖范围 = agent 可以放心依赖的脚本集合。

**现状**

| | world_script_execute | agent_goal_run |
|---|---|---|
| 数据 | v1：106 例、覆盖 38 个脚本（目录共 39 个）、19 个存档 | v1：20 条、6 类、全 `val`、全空记忆、`max_steps=15` |
| 最近结果 | 10-08 修复后 v1 两轮 212/212，无 flaky；尚未验证新的 31 个公开契约 | 10-08 两条冒烟均 invalid，未进入模型执行；存档与 memory MCP/checkpoint 阻塞见 plan 实测记录 |

---

## 二、world_script_execute

### 2.1 公开能力与操作流程（用户已确认）

公开能力目录的集合必须恰好等于下表 31 个名字。按当前场合给出其中可用的子集；
内部恢复、移动光标、填数量、等待稳定、固定流程确认与核对结果均由 world 完成。
不把菜单层数、常规/接管来源或内部策略的名字交给 agent 选择。

| # | 公开脚本 | 简单流程 / 返回边界 |
|---|---|---|
| 1 | face_direction | 已面向则不动，否则按一次方向键；保留当前可能同时位移的语义，如实报告 moved |
| 2 | walk_to_adjacent | 按指定方向走一次，核对位置；报告到位、被挡或中途事件，台阶可能跨两格 |
| 3 | walk_to | 逐步缩短到目标坐标的距离，被挡尝试另一轴；到位、不收敛、预算耗尽或中断时返回，不承诺 BFS 寻路 |
| 4 | exit_map | 查本图出口，走到触发位置并移动，核对已经换图 |
| 5 | seek_encounter | 检查草丛起点，内部重复移动；遇怪返回 battle_started，预算用完如实报告未遇怪，不声称已经遇怪 |
| 6 | interact_facing | 对面前对象按 A，报告对话/菜单/无响应，保留后续普通对话给 agent |
| 7 | talk_to_adjacent_npc | 核相邻 NPC、面向并交互，推进普通对话到结束；出现分支选项或战斗即返回 |
| 8 | advance_dialog | 推进已有对话，收集文字；结束、选项、战斗或预算耗尽时返回 |
| 9 | wait_until_scene | 只推进帧，反复检查指定场合；达到或超时即返回 |
| 10 | open_menu_to | 打开开始菜单，按实际选项选目标，核对目标界面 |
| 11 | close_menu | 按当前菜单选择退出路径并逐层返回，核对离开整个菜单操作；不能代答学招、命名、剧情或战斗决策 |
| 12 | heal_at_center | 核中心布局，走到护士前，对话并确认治疗，核对全队满血 |
| 13 | buy_item | 核商店/商品/数量/钱，完成购买菜单流程，核钱减少与背包增加 |
| 14 | sell_item | 核库存/数量/可卖性，完成出售菜单流程，核钱增加与背包减少 |
| 15 | battle_fight | 核招式与 PP，选择招式，推进战斗文字到下一决策点或战斗结束 |
| 16 | switch_pokemon | 核可派出的目标，按主动换人/倒下后派人分别执行，核在场队员；保留不同回合规则 |
| 17 | battle_run | 核允许逃跑，选择 RUN，推进文字并报告逃走或未逃掉 |
| 18 | use_item | 核道具/对象，按战斗或野外分派内部实现，核消耗与效果；投球推进到捕获结果或下一决策点 |
| 19 | toss_item | 核背包道具/数量/重要道具限制，丢弃并核数量变化 |
| 20 | reorder_party | 核两只不同队员，完成换位，核队伍顺序 |
| 21 | use_field_move | 核队员/招式/支持范围，选择野外招式并核结果；未实现的目的地选择明确拒绝 |
| 22 | pokemon_stats | 找指定队员，打开能力页后返回，供 agent 读取；不自动关闭 |
| 23 | pc_withdraw_item | 核 PC 库存和背包容量，取指定数量，核 PC 减少、背包增加 |
| 24 | pc_deposit_item | 核背包库存和 PC 容量，存指定数量，核背包减少、PC 增加 |
| 25 | pc_toss_item | 核 PC 库存/数量/重要道具限制，丢弃并核 PC 数量 |
| 26 | pc_withdraw_pokemon | 核当前箱目标和队伍空位，取出并核队伍/箱变化 |
| 27 | pc_deposit_pokemon | 核目标、至少留一只队员和箱容量，存入并核队伍/箱变化 |
| 28 | pc_change_box | 核箱号，换箱并完成固定流程确认，核当前箱号 |
| 29 | enter_name | 核名字，清已有输入、逐字输入并提交，核结果 |
| 30 | learn_forget | 核指定旧招，忘掉并学习新招，核招式替换 |
| 31 | learn_skip | 明确选择放弃学招并确认，推进到退出本次流程 |

合并 use_item 的签名保留 `item` / `pokemon`，switch_pokemon 保留 `pokemon`；
close_menu 无需让调用方指定内部菜单种类，seek_encounter 保留有限移动预算。
其他只是改名的操作保留原参数含义；具体类型、默认值及失败码先在接口/能力声明定清楚，再实现。
公开目录必须登记可用场合、业务参数、停止条件和可返回失败码，成为掩码与分发共同消费的真源。

可用场合的基线：switch_pokemon 支持战斗行动菜单与战斗队伍列表；use_item 支持战斗行动菜单
与野外背包；close_menu 支持开始菜单、能力页、野外背包、野外队伍、商店菜单和 PC 的退出路径，
拒绝战斗队伍列表等必须另作决策的场合。其余沿用已有有效入口；本轮不要求所有业务脚本都能
从野外自动打开菜单。内部脚本可以打开/恢复所属菜单，但不能自动决定无关业务分支。

### 2.2 公开/内部边界与旧名迁移

**公开目录与内部执行注册表分开。** 内部实现仍可按地图、菜单、战斗等业务组织，
采用统一执行器与各自策略；world 内部可以调用内部实现。模型动作空间、门面层、MCP 工具列表
以及 MCP 通用脚本调用只认识公开目录。外部猜到内部名字也必须具名拒绝且不产生游戏副作用；
不是仅在掩码里隐藏，更不以 assert 校验外部输入。

| 旧名 | 对外收敛 | 内部处理 |
|---|---|---|
| shop_buy / shop_sell | buy_item / sell_item | 前两者仅 world 内部调用；不保留外部别名 |
| battle_switch / switch_send_out | switch_pokemon | 按战斗阶段选实现；不能把倒下后派人算成主动换人的一回合 |
| bag_use / battle_use_item | use_item | 野外/战斗校验与效果分开，公开参数统一 |
| bag_close / party_close / shop_quit / pc_log_off | close_menu | 按场合退出；包括嵌套列表，不误选业务操作 |
| bounce_in_tall_grass | seek_encounter | 蹦跳是内部移动策略；保持预算与遇怪结果可核对 |
| circle_walk | 无独立公开能力 | 仅内部策略/回归用法，外部不能指定“绕圈脚本” |
| bag_toss / party_switch / party_field_move / party_stats / naming_enter_name | toss_item / reorder_party / use_field_move / pokemon_stats / enter_name | 按新业务名对外，其余规则不因改名改变 |
| 其余 22 个名字 | 保留 | 纳入同一公开目录，不标常规/接管 |

旧名和内部名不作为生产外部调用的兼容别名。既有 v1 冻结文件与历史 trace 不重写；
v1 的旧名仅能经隔离的本地回归适配器执行，不能成为 MCP/生产入口的旁路。
v2 迁移语义相同的旧用例，内部步骤用例归 world 集成测试。只核 shop_buy 等内部菜单步骤的
旧用例不能直接改名成外层完整操作：须补齐外层入口和钱/背包等独立效果判据。
agent prompt、动作签名、维护中的知识先验和新 oracle 使用新名字；历史账本保留原貌。

### 2.3 口径与覆盖规则（v2 验收线）

一条公开用例 = 存档 + 开跑前按键 + **一次公开脚本调用** + 期望；内部按键或子调用次数不限。
判两面：code（自报 ok/code/data/events）与 truth（前后 RAM 及读屏独立效果），两面都过才算 pass。
测评在本地真实模拟器上直接调用 world 的公开脚本函数或公开分发器，不经过 harness、GameTools
或 MCP；只测完整操作是否有效，不独立检查外部调用链或内部步骤。`model="none"`。
after/delta 与 checks/status 两套既有真值词表继续使用，但采用公开语义判结果。

| 编号 | 规则 |
|---|---|
| C1 | 31 个公开脚本各 ≥1 条成功用例；合并操作的每个业务入口另有成功示范：主动/倒下后换人、野外/战斗用道具、close_menu 各支持入口 |
| C2 | 每个公开脚本可达的失败出口 ≥1 条 failure 用例；按公开名和必要的入口分支登记。内部失败只在会透传成公开结果时计入，不按内部实现名强制凑齐 |
| C3 | walk_to、walk_to_adjacent、seek_encounter、exit_map、heal_at_center、talk_to_adjacent_npc、advance_dialog、wait_until_scene 共 8 个公开能力各 ≥1 条开跑后发生的 interrupt 用例；以世界真值定案，不能把起点已在战斗计作中途干扰 |
| C4 | 每条用例真值面非空，关键业务有独立效果核对；不能只信脚本自报 |

C3 不要求一律 ok=false：seek_encounter 的遇怪是目标达成，必须报告实际成功；
护士固定 YES/NO 确认是治疗流程，不算意外干扰。等待只 tick，必须从会自动发生事件的过场快照
构造干扰，不能用稳定野外等待捏造遇怪。内部绕圈的现有实测只证明内部策略，不抵充公开脚本覆盖。

覆盖工具按 **公开脚本 × 业务入口 × {success, 各公开 failure code, interrupt}** 输出计数与缺口。
v2 默认读公开目录，不再用整个 SCRIPT_FUNCS 当分母；v1 单独标为历史实现覆盖，不与 v2 指标合并。
出口登记由人核源码与真实模拟器可达性；当前保守登记的共享超时/恢复出口不是已证可达事实。
不可达项须有依据后从公开登记中排除；内部恢复、异常和契约路径在集成测试中验证，不伪造正常游戏存档。
脚本自身的非法业务参数或不可用对象属于 C2；外部入口拒绝内部/退役名字属于集成测试，不计 C2。
调用方式保持 `python -m evals.dataset.world_script_execute.build.coverage --version v2`；
数据错误、功能未覆盖或功能清单不一致以非零退出结束；不把外部边界测试结果并入覆盖工具。

ScriptCase.kind 保持 success/failure/interrupt；v2 必填，v1 按 expect.ok 推导且不改冻结文件。
v2 增加有类型的业务入口标识供合并操作分组，用例内不存内部分发函数名。

### 2.4 当前进度与回归依据

W1 分类、指标和旧实现覆盖工具已完成。旧目录共 39 项，v1 覆盖 38 项；wait_until_scene 无用例，
party_field_move、pc_withdraw_pokemon 无成功用例。该表是历史盘点，不能作为新公开 API 的验收表。
W2 已修复 switch_from_party_list 的入口拒绝；原期望未改，四条换人各两轮通过。
v1 全量两轮 212/212、无 sample error、无 flaky、零模型调用；这不证明新合并能力已通过。
已有候选与证据见 world-v2-cases-draft.md / world-v2-coverage.md，实施前按新目录重新归类。

### 2.5 确定性与数据冻结

v1 文件保持冻结。v2 根据迁移表重组公开用例，不能整份复制 106 条再追加；迁移清单逐条说明
保留/改名/合并/转集成测试和真值变化理由。只冻结用户选定且真实执行核实的候选。
`--epochs 2` 下任何公开用例两轮结论不同即 flaky；sample error 单列，不能当作成功或稳定。
不新增日志比较器，pass 均值 0.5 可定位两轮评分波动，检查日志同时确认无 sample error。

### 2.6 指标

pass/code/truth 的 accuracy 保留；pass 按公开 script、kind 与合并操作业务入口分组。
kind_accuracy 使用已落地的独立指标名，避免多个同名 grouped 被 Inspect 合并。
报告仅附 31 项功能清单、业务场景覆盖表及效果结论；外部边界、内部回归与历史 v1 结果不进功能成功率。

### 2.7 集成测试的职责（与功能测评分开）

- 外部调用：核动作空间、门面与 MCP 的公开名字和参数分发；内部/退役/未知名拒绝且游戏状态不变。
- 内部回归：通过真实组合流程核菜单恢复、光标导航、数量填写、等待、分支和子调用协作。
  不按私有函数数量机械补测试，不把内部执行器名字当公开功能。
- 集成测试放 tests，不注册新 Inspect task，不加入 world_script_execute 的样本、分数、覆盖分母或报告验收线。
  本轮先完成脚本功能测评；外部链路探活或集成回归执行不是运行本地功能测评的前置条件。
  公开/内部的架构约束仍保留，边界是否正确接线由集成测试单独回答。

---

## 三、agent_goal_run

### 3.1 口径（保持）

一条样本 = 打包存档 + 一个目标；子进程跑完一个 run。成败以**机械判据为第一真源**，红线命中即判负，模型结果分独立一列。路径、步数、成本只用来诊断，不进分数。

### 3.2 现状问题

| 编号 | 问题 |
|---|---|
| P1 | **重构后没跑过**。406 / 407 / 421 之后 0 次真机运行；存档是 09-29 打包的，`state_schema_hash` 是否仍和现行代码一致不知道（不一致会被 `restore_run` 拒载，记 `invalid`） |
| P2 | **判据口径不一致**。SPEC 写"按最终结果判"，但规则里大多是 `first_match`（只要"出现过"就算），模型结果分则只看最后一帧。两列会系统性分歧，例如打开过商店菜单、随后又退出 |
| P3 | **题太浅**。20 条全是单屏一步的变化。有了脚本之后，不少条一次脚本调用就能完成，测不出项目主张的长程能力 |
| P4 | **样本本身没验证过**。没有证据表明每条在 `max_steps` 内可解，也没证明"什么都不做"时判据不会误判成功 |
| P5 | **死字段**。`rubric`（两条 human、一条 code，都没实现）、`k_metric`（epochs 一直是 1）；`scorers/agent_goal_run/metric.py` 自述"R5 后退役" |
| P6 | **评分模型不独立**。评分模型和被测系统同为 deepseek-flash；对 19 条可机械判定的样本它是冗余列，只在 1 条不可判样本上真正有用，却从没校准过 |
| P7 | **失败没有归因**。只有"判负"一个结论，分不清是脚本坏了、判定员误判、停摆，还是预算耗尽 |
| P8 | `knowledge_battle_pokemon_switch` 没有机械判据。decode 现在能识别 `battle_switch` 场合，可以补上 |

### 3.3 判据分两型（E1）

| 型 | 含义 | 判法 | 现有例子 |
|---|---|---|---|
| `event` | 目标是"某件事发生过" | run 内**起点之后**的任意一帧满足即 pass | 遇怪、对话出现、招式打出、投球 |
| `final` | 目标是"停在某个状态" | 只看最后一帧（带 RAM 的末帧） | 到达位置、对话框消失、队伍满血、买到东西（钱和背包的差值） |

- 型登记在规则上：`@rule("move_used", mode="event")`。`judge()` 按型切帧，规则只写单帧谓词，不再各自决定看哪些帧。
- **起点自检**：规则在起点帧上必须判 fail；判 pass 说明样本无效（起点已满足目标），由 §3.4 的 V2 兜住。
- 模型结果分的输入随型变化：`final` 给末帧观测；`event` 给全程解码文字去重后的序列加末帧。
- v1 的 18 条规则逐条定型，草稿表见 plan，由用户确认。

### 3.4 样本自检（新，E2）

每条样本冻结前必须通过两项检查：

| 编号 | 检查 | 通过条件 |
|---|---|---|
| V1 可解 | 脚本化大脑按样本附带的 `oracle`（脚本调用或按键序列）逐步出决策，从存档跑**真 harness** | `max_steps` 内机械判据 pass，红线全空 |
| V2 零动作对照 | 脚本化大脑只做无效动作，然后宣布完成 | 机械判据 fail，并命中 R3 |

- 脚本化大脑 = 实现 `BrainPort` 七个方法（choose / reflect / judge / plan / decompose / verify / summarize）的 mock，按 AGENTS 铁律 4 与真实现同一个 Protocol，经装配点注入，不调模型。
- `oracle` 存在样本上（`EvalSample.oracle: list[OracleStep]`）。v1 的 20 条补一份写进 v2，v1 文件不改。
- 顺带兑现 AGENTS 第十节登记的技术债（"FakeLLM 跑完整 episode"）。但它依赖 ROM（不进 git），所以作为 `build/validate.py` 工具，不进默认 pytest。
- **可行性风险**：要求装配点能换掉 brain 而不改生产代码。plan 第一步先做 spike，不行就退到备选方案（只在 world 层验可达）。

### 3.5 数据集 v2：三档（E4）

| 档 | 条数 | 内容 | 判据 | 切分 |
|---|---|---|---|---|
| L1 原子 | 20 | v1 原样迁入，补 `oracle`；pokemon_switch 补判据 | 两型都有 | val |
| L2 组合 | ≈10 | 同图或相邻图里串 2–4 个子目标，必须跨 task 才能完成 | 以 `final` 为主（钱、背包、HP、map_id、坐标） | val |
| L3 长程 | ≈5 | 跨多张图、多个 episode | `final` | **test**（只在里程碑跑，不拿来调 prompt） |

- L2 / L3 的具体目标在 plan 里列草稿表，由用户勾选；`max_steps` 取 oracle 步数的 2–3 倍。
- 样本加 `tier`，指标按 tier 分组。
- 记忆起点仍然全空；非空记忆起点留到 §3.8。

### 3.6 评分列

| 列 | 内容 | 进成功率 |
|---|---|---|
| `e2e_scorer`（主列） | 机械判据 + 红线 → `judged_accuracy` / `judged_count`，按 `tier`、`category` 分组 | 是 |
| `failure_class` | §3.7 的归因，放 metadata 并分组计数 | 否 |
| `result_model_scorer` | 评分模型换成独立型号（E3）；额外报告它和主列的**一致率**（只在两列都可判的样本上算）。一致率 < 90% 时，不把模型列用于不可机械判样本的结论 | 否（单列） |
| 诊断列 | act 次数、脚本调用次数、模型调用次数、输入 / 输出 token、墙钟秒，从账本读，放进 `Score.metadata` | 否 |
| pass@k / pass^k | `--epochs k` 时由 inspect reducer 出；正式基线 k=3 | — |

sample error（基础设施故障）和 NOANSWER 单独披露，都不进分母。

### 3.7 失败归因（新）

纯函数 `(RunStream, EvalSample, CheckVerdict) -> FailureClass`，只用账本上能机械确定的事实，不猜"大脑为什么错"。从上往下取第一个命中的：

| 类别 | 判据 |
|---|---|
| `infra_invalid` | `AgentRunRecord.invalid` 非空（存档拒载、超时） |
| `run_error` | 命中 R1 |
| `false_success` | 命中 R3（`goal_done` 收尾但机械判 fail）——判定员假阳 |
| `missed_success` | `event` 型判据在某帧已经 pass，或 `final` 型的目标状态曾经出现过，但 run 没有以 `goal_done` 收尾——判定员假阴，或者没停下来 |
| `script_crash` | 有 `act_call` 是脚本抛异常（不是正常的 ok=false） |
| `stalled` | run 或 episode 以 `stalled` 收尾 |
| `budget_exhausted` | 以 `budget_exhausted` 收尾 |
| `other` | 以上都不是 |

验收要求 `other` ≤ 10%；超过说明分类不够用，要先补类别。

### 3.8 记忆对照（可选，E5）

在同一个 v2 val 集上，`knowledge=true` 和 `false` 各跑 k=3，报告成功率差值及置信区间。这是项目主张最直接的证据；机制一和机制三尚未实现，所以本轮只对照知识库。

### 3.9 成本控制

- 单样本 `timeout` 保持 3600 秒。P0 实测每条样本的 token 和墙钟，估出全量成本；超出用户给的预算前先停下来问。
- 样本各自在子进程里起模拟器，可以 `--max-samples > 1`，默认值等实测后再定（进程内 pyboy 的锁只约束 world solver）。

---

## 四、不做什么

- 其余四个 task。
- 合并 world 的两套真值词表。
- 路径 / 过程打分（rubric 的三条，本轮删除，不实现）。
- 非空记忆起点、多目标 run、续跑。
- 状态表在线归并（机制一）与 MC 回填（机制三）本身。

## 五、成功样子

**world_script_execute**
- 31 个脚本的本地真实模拟器功能用例覆盖达标，覆盖工具退出码为 0（C1–C4 满足）。
- 按脚本、kind 和业务场景统计；外部调用与内部回归放集成测试，不作为本 task 的通过条件。
- 全量 `pass` 失败数为 0；剩下的每一条都有登记的缺陷说明。
- `--epochs 2` 无 flaky。

**agent_goal_run**
- v2 每条样本都通过 V1 / V2。
- k=1 冒烟 0 条 `infra_invalid`。
- k=3 基线报告（`docs/experiments/`）包含：分 tier 的 pass@1 与 pass^3、红线命中率、`failure_class` 分布（`other` ≤ 10%）、机械列与模型列的一致率、每条样本的平均成本。
