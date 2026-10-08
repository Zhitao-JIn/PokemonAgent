# plan —— world_script_execute 与 agent_goal_run 的下一版

> 流程位置：world-e2e-spec.md → **world-e2e-plan.md** → PR
> 每一步落地时占一条 CHANGELOG 编号条目、独立 commit（AGENTS 第三节第 6 条）；编号落地时再取，本文件不预占。
> 原计划标为「用户跑」的 world 验证已能由 Codex 在本机执行（Windows venv + ROM）；模型费用仍按成本闸处理。本次只更新文档，新增 31 项公开能力尚未实施。

---

## 〇、总顺序与闸门

```
P0 现状核验（world 已通过；agent 存档/MCP 阻塞见实测记录）
 ├─ W 线：W1 旧覆盖工具 ✓ → W2 修 switch ✓
 │        → W5 公开/内部目录隔离 → W6 能力合并与消费者迁移
 │        → W3 公开用例迁移草稿 ⟶[用户勾]⟶ W4 冻结 v2 + 确定性
 └─ E 线：E1 判据定型 → E2 归因 + 诊断列 → E3 评分模型独立
          E4 脚本化大脑 spike ⟶[可行?]⟶ E5 自检工具 → E6 v2 草稿 ⟶[用户勾]⟶ E7 冻结 v2
          E8 清死字段
G 基线：v1 k=1 → v2 k=3 ⟶[成本闸]⟶ 报告 →（可选）记忆对照
```

- W5/W6 的 31 项公开目录已由用户确认，不再等目录选择；W3 的新增存档/用例仍按草稿勾选。
- E1–E3 的评分代码可以独立推进；实际 agent 运行先排除 P0 阻塞，W6 后还要核对公开名字与 prompt/oracle 的接线。
- G1 不必等 v2 数据，但必须记录所用公开 API/代码版本；旧 v1 world 的 212/212 不代表新目录验收。
- 三个闸门需要用户拍板：W3 / E6 的草稿表勾选、E4 的可行性结论、G2 之前的成本估算。

---

## P0 —— 现状核验（不改代码，用户跑）

| # | 命令 | 期望 | 不符时 |
|---|---|---|---|
| 0.1 | `python -m evals run world_script_execute --log-dir eval_results/world_script_execute` | 已完成：修复前 105/106，W2 后两轮 212/212；后续新目录单独验收 | 旧结果保留作回归依据，不重新要求出现已修复的失败 |
| 0.2 | `python -m evals run agent_goal_run -T samples=[knowledge_door_transition] -T log_dir=eval_results/agent_goal_run --log-dir eval_results/agent_goal_run` | 1 条跑完，不是 `invalid`；Inspect View 的 Transcript 能看到回放 | `invalid` 且原因是存档拒载 → `python -m evals.dataset.agent_goal_run.build.pack` 全量重打再跑；重打失败先核 `checkpoint_error` |
| 0.3 | 同上，再跑 `knowledge_shop_open_buy_menu`（09-29 停摆的那条） | 记下成败 | — |

**产出**：两条样本的 token 用量、墙钟、模型调用次数（Transcript 里有），用作 §G 的成本估算。把数字贴回本文件末尾的「实测记录」。

运行前核对 `.env` 的 MCP 地址及对应服务探活。Windows 命令环境设 `PYTHONUTF8=1`，避免 pack 的 ✓ / ✗ 输出触发 GBK 编码错误。`-T log_dir` 控制子进程产物目录，`--log-dir` 控制 Inspect 日志目录，两项都传才能同根。

---

## W 线 —— world_script_execute

### W1 覆盖工具 + kind（已完成，旧实现口径）

- 已有 v1 分类兼容、版本缺 kind 检查、覆盖 CLI 与人工失败码登记。
- 已有 task metadata 的 kind 与独立 kind_accuracy 指标；不能并列两个同名 grouped，否则 Inspect 会合并。
- 旧工具分母是 SCRIPT_FUNCS，共 39 个实现；保留其 v1 历史输出。W3 必须改成公开目录/业务入口口径。
- 验证与 commit 见实测记录和 CHANGELOG 422；不重新占编号。

### W2 修 switch_from_party_list（已完成）

- 根因是队伍列表场合在准备阶段之前被拒绝；已增加显式 entry_scenes，能力目录与执行器共用。
- 期望未改；四条 battle_switch 各两轮通过，全量 v1 两轮 212/212。
- CHANGELOG 423 的修复作为 W6 合并换人的回归依据；不保留旧名作公开兼容别名。

### W5 公开目录与内部执行边界（新增，先于用例迁移）

1. 先在 world 自有接口/能力声明中写清公开调用契约：参数、适用场合、前置条件、停止条件、结果与失败码。
   按 spec §2.1 登记 31 个名字；新增公开目录，内部实现注册表留 world 内部。
2. 模型动作签名、world action_space、GameTools 掩码、MCP 工具列举和通用脚本分发都消费同一公开目录。
   不只改 SCENE_SCRIPTS：核对 MCP 通用入口是否仍按 SCRIPT_FUNCS 接受任意内部名字。
3. 外部内部名/退役名/未知名走具名拒绝，不能按内部表执行，不用 assert 处理外部输入。
   拒绝报告沿既有响应与 trace 链留痕；trace 记录外部请求的公开调用，不给内部子调用另造 agent 动作。
4. world 内部专用调用可以使用内部实现，但其入口不出 Port/MCP/门面层；内部依赖不反向引用 harness。

**功能实施检查**：本地公开功能清单与 spec 表逐项相等且数量 31，模块 Port 不引入本项目 Req 信封。
W5/W6 允许分步接线，但不把尚未实现的能力发布给模型；本地功能测评不等待外部服务探活。

### W6 能力合并、改名与消费者迁移（新增）

按 spec §2.2 的完整映射分步实施，各步一条 CHANGELOG，不混进评分或 agent 架构改动：

| 分步 | 变更 | 必须保留的区别与验收 |
|---|---|---|
| W6a 换人 | battle_switch / switch_send_out → switch_pokemon | 主动换人与倒下后派人分别验；名单/倒下/已在场校验、对手回合影响、收尾 RAM 均不失真；队伍列表入口回归 |
| W6b 道具 | bag_use / battle_use_item → use_item；bag_toss → toss_item | 野外/战斗分别验；药物、球、对象与不可用校验保留；道具消耗和 HP/捕获结果独立核对 |
| W6c 退出 | bag_close / party_close / shop_quit / pc_log_off → close_menu | 各业务菜单和嵌套列表退出；开始菜单与能力页补退出示范；不代答战斗、学招、命名或剧情选项 |
| W6d 遇怪 | bounce_in_tall_grass → seek_encounter；circle_walk 内部化 | 有限预算，报告实际遇怪/未遇怪；内部策略名字不外泄；遇怪成功不误判成失败 |
| W6e 其他名字 | party_switch / party_field_move / party_stats / naming_enter_name → reorder_party / use_field_move / pokemon_stats / enter_name | 原参数与效果保留；不把未支持的野外招式改成已支持 |
| W6f 商店与接线 | shop_buy / shop_sell 只内部调用；保留的 22 个旧名包含公开 buy_item / sell_item | 外层完整操作与对账仍执行；公开目录、签名、参数和场合契约一致 |

- 扫消费者：catalog、world/action_space、mcpclient/game_tools、world MCP 服务、prompt/动作说明、维护中的知识先验、evals 和 oracle。
  维护中的配置/先验改用公开名字；历史 trace、冻结 v1、历史实验报告不批量改写。
- 合并参数与默认值先声明再实现。按当前场合分派，不要求无关脚本从野外自动开菜单。
- 功能 solver 本地直接调用 world 公开脚本函数或公开分发器，不经生产门面/MCP。
  旧 v1 日志可继续读回评分；只核内部步骤的旧用例不进入新功能数据集。

**功能验收**：每个合并/改名能力有本地完整操作示范，关键业务场景分别验证报告与 RAM/读屏效果。
同步 world spec 的公开契约，但不宣称新 v2 全量通过；完成后再做 W3 的数据迁移。

### W3 公开用例迁移与补齐草稿（W5/W6 后，⟶ 用户勾）

1. 为旧 106 条逐条登记保留/改名/合并/排除，不整份照抄。更新 world-v2-cases-draft.md：
   每行写公开名、业务入口、kind、起点、pre、参数、期望 ok/code/独立真值、来源 case_id 和依据。
2. shop_buy/shop_sell 的旧菜单步骤用例排除，或重构成调用完整买卖功能的效果用例。
   circle_walk 的绕圈/干扰证据留内部策略；不能直接计公开 C1/C3。
3. 扩展 ScriptCase 的有类型业务入口标识；覆盖工具 v2 用公开目录为分母，失败码按公开分支登记，
   各合并操作的入口分别计数；v1 输出明确标历史实现覆盖，不混入 v2。
4. 补 C1：真正等待过场、use_field_move 成功、pc_withdraw_pokemon 成功及所有合并操作的业务入口。
   用额外快照固定起点，准备阶段不算被测脚本的第二次公开调用。
5. 补 C2：只要求脚本功能可返回且模拟器可达的出口；共享引擎保守登记先做可达性审核。
   不为凑覆盖篡改 RAM 造正常游戏不可能的状态。
6. 补 C3：spec §2.3 的 8 项；固定存档+按键各实测两轮，独立 RAM/读屏证明确是开跑后干扰。
   seek_encounter 遇怪报告成功；中心护士正常确认不算干扰；wait 需自动事件快照。

**产出**：公开目录/入口覆盖草稿、逐条迁移清单和可复查的原始执行记录。
已实测的 8 条拒绝/等待候选、bounce/circle 探测记录可复用为依据，但需按新公开名字重跑，不能视为新契约验收。

### W4 冻结 world v2 + 功能确定性

- 按勾选的迁移清单重组 v2/cases.jsonl，复制实际引用的状态到 v2/states；kind 和业务入口必填。
  不改 v1，不把内部脚本名或内部来源当成公开类别；正式 task 默认 v2。
- 功能 solver 本地调一次完整公开操作，不经过 harness/GameTools/MCP，不把内部子步骤单独计为功能样本。
- 本机跑：`python -m evals.dataset.world_script_execute.build.coverage --version v2`，
  `python -m evals run world_script_execute --epochs 2 --log-dir eval_results/world_v2`。
- **验收**：C1–C4 通过；功能 pass 全过或剩余失败逐条登记；sample error 0；两圈无 flaky。
  报告只按脚本/kind/业务场景分组。同步 docs/spec/evals/SPEC.md 与 world 的功能契约。

---

## E 线 —— agent_goal_run

### E1 判据定型（event / final）

- `evals/scorers/registry.py`：`rule(check_id, *, mode: Literal["event", "final"])`，`RULES` 里存 `(mode, fn)`。
- `judge()` 统一切帧：先取 `target_frames`，去掉**起点帧**（第一条带 RAM 的帧）之前与本身；`event` 型把帧序列交给规则，`final` 型交 `(起点帧, 末帧)`。规则函数体只留谓词，不再自己调 `first_match` / `ends`。
- 起点自检挪进 `judge()`：谓词在起点帧上为真 → `unjudgeable("起点已满足目标")`（这类样本由 E5 的 V2 拦截，不该进集）。
- 18 条规则的定型草稿（按现行代码推出，用户确认后照此改）：

| check_id | 现行做法 | 拟定型 | 备注 |
|---|---|---|---|
| battle_started | 任一帧战斗标志 | event | |
| cursor_on_run | 任一帧光标在 RUN | event | |
| move_list_opened | 任一帧招式列表 | event | |
| move_used | 对手 HP 比开局低，或出现结算字样 | event | 结算字样只能逐帧找 |
| bag_opened_in_battle | 任一帧战斗背包 | event | |
| run_attempted | 离开战斗或出现 escape 字样 | event | |
| foe_hp_dropped | 对手 HP 比开局低 | event | HP 可能回复，用 event 更宽容 |
| ball_thrown | 精灵球比开局少 | **final** | 背包数量只减不增，末帧即可 |
| party_healed | 开局有人受伤、之后某帧全满 | event | 若希望"结束时仍满血"改 final |
| dialog_opened | 任一帧有对话且无选单 | event | |
| dialog_finished | 出现过对话 + 末帧没对话框 | **混合** | 拆成 final（末帧无框）+ 起点自检（起点有框） |
| map_changed | 末帧 map 与开局不同 | final | |
| reach_map12_y14 | 末帧位置 | final | |
| shop_menu_opened | 任一帧 BUY/SELL/QUIT | event | |
| shop_list_opened | 任一帧带价格的列表 | event | |
| shop_item_selected | 任一帧确认框 | event | |
| shop_bought | 钱少了、背包某物多了 | final | |
| shop_cancelled | 末帧是列表且钱没变 | final | |

- 补 `knowledge_battle_pokemon_switch` 的规则 `party_list_opened_in_battle`（event：task 场合为 `battle_switch`）；样本的 `check_id` 在 v2 里填上（v1 文件不改）。
- **验收**：`tests/test_evals_checks.py` 按新签名更新、全过；用 09-29 的 5 条旧 run 账本（`eval_results/inspect/runs/`）回放判定，结论与当时一致，有出入的逐条说明。

### E2 失败归因 + 诊断列

- 新增 `evals/scorers/agent_goal_run/attribution.py`：`FailureClass`（StrEnum，spec §3.7 的 8 类）+ 纯函数 `attribute(stream, sample, verdict, record) -> FailureClass`。读的账：`run_end` / `episode_end` 的 `termination`、`act_call` 的脚本报告、红线结论。
- `missed_success` 需要"目标状态曾出现过"：`event` 型直接复用判据；`final` 型对每帧跑一遍 final 谓词（以起点帧为基准）。
- 诊断列：从 `RunStream` 数 `act_call`（按键 / 脚本分开）、`*_call` 模型账的条数与 token 用量，加墙钟（`run_start` 到 `run_end` 的 ts 差）。放进 `e2e_scorer` 的 `Score.metadata`。
- `e2e_scorer` metadata 加 `failure_class`；新增 metric 按类计数（只统计判负样本）。
- **验收**：单测覆盖 8 类各一个最小账本（按 AGENTS 第三节第 5 条：走公开出口、读起来像用法示范）；09-29 旧账本里停摆的那条归为 `stalled`。

### E3 评分模型独立 + 一致率

- `agent_goal_run` 的 `grader_model` 缺省值改读 `evals/config.json` 的 `evaluation_models.result_grader`，不再写死。**型号由用户定**（要求和被测系统的五个模型位都不同）。
- `result_model_scorer` 的输入按 E1 的型切换（final：末帧观测；event：全程解码文字去重序列 + 末帧）。
- 一致率：新 metric 只在两列都为 C/I 的样本上算 `mech == model` 的比例；放在 `result_model_scorer` 上，需要读主列结论——两列的交接走 store（参照 `AgentRunRecord`），不反读 transcript。
- **验收**：用假模型（inspect 的 `mockllm`）跑通一条，确认解析和 NOANSWER 路径都正确。

### E4 脚本化大脑 spike（⟶ 可行性结论）

先只读、不写代码，回答三个问题，结论写回本文件：

1. `BrainPort` 七个方法里，跑完一个单目标 run 实际会调用哪几个？各自返回什么结果袋？（`brain/interface/brain_port.py` + `harness` 的调用点）
2. 装配点能否不改生产代码就换掉 brain？现在 `build_real` 经 `BrainTool.build(text=…)` 内部造 `Brain`。如果没有注入口，最小改动是什么（例如 `BrainTool` 收一个现成的 `BrainPort`）？这个改动是否符合 AGENTS 第二、三节？
3. oracle 用什么形状最省事：脚本调用序列（大多数 L1 一两次脚本调用就够），还是按键序列？

**闸门**：可行 → E5；不可行 → 退到备选方案（world 层用 `start_world` + 脚本序列验可达，再对末帧跑 final 谓词；不验 event 型和红线），spec §3.4 相应改写。

### E5 样本自检工具

- `evals/dataset/agent_goal_run/build/validate.py`：对每条样本跑 V1（按 oracle）和 V2（零动作然后宣布完成），产物落 `eval_results/validate/<sample>/`，结论表输出到 stdout，有不通过的退出码为 1。
- `schemas.py`：`OracleStep`（`script` + `args`，或 `keys`）；`EvalSample.oracle: list[OracleStep] = []`；v2 必填。
- v1 的 20 条补 oracle → 写进 v2 草稿（E6）。
- **验收**（用户跑）：L1 20 条全部通过 V1 / V2；不通过的逐条处理（改样本或记为 world 缺陷）。

### E6 v2 草稿（⟶ 用户勾）

`docs/eval/agent-v2-samples-draft.md`，每行：tier、目标、`success_criteria`、check_id（新规则写出谓词）、mode、起点存档、oracle 概要、`max_steps`。**以下候选的起点都要先实测核实**（游戏进度会影响能不能买东西、能不能遇怪）：

**L2 组合（候选 12 条，选约 10 条）**

| 候选 | 判据（final） | 起点 |
|---|---|---|
| 从门外进宝可梦中心并治好队伍 | map 是中心 且 `party_hp_missing = 0`（起点需有人受伤） | center_enter |
| 买 3 个精灵球并走出商店 | `bag:POKé BALL` +3，钱 −600，map ≠ 商店 | shop_interaction |
| 卖掉一个道具并走出商店 | 背包 −1，钱增加，map ≠ 商店 | shop_interaction |
| 遇怪、削血、投球捕获 | 队伍数 +1（或 PC 数 +1） | wild_encounter |
| 战斗中用伤药后逃跑 | HP 高于起点且 scene = walk | battle_low_hp |
| 绕过障碍走出地图北口 | map_id 变成相邻图 | movement_obstacle |
| 和 NPC 说完整段话并回到原位 | 末帧坐标 = 起点，无对话框 | npc_dialogue |
| 从 PC 取出一个道具并退出 PC | 背包 +1，scene = walk | pc_save |
| 队伍第 1、2 位换位并关闭菜单 | 队伍顺序对调，scene = walk | field_two_mons |
| 学新招式时忘掉指定旧招 | 指定招式在列、旧招不在 | learn_move |
| 打开菜单存档后回到野外 | 存档计数 / 标志变化（需确认 RAM 地址），scene = walk | pc_save |
| 打赢一场野生战斗 | 对手消失且 scene = walk，经验值增加 | wild_encounter |

**L3 长程（候选 6 条，选约 5 条，切分 test）**

| 候选 | 判据（final） |
|---|---|
| 从 1 号道路走到常磐市宝可梦中心并治疗 | map 是常磐中心 且 `party_hp_missing = 0` |
| 到常磐商店买 5 个精灵球再回中心 | 背包 +5 且 map 是中心 |
| 在草丛抓一只宝可梦后回中心治疗 | 队伍数 +1 且 `party_hp_missing = 0` |
| 从真新镇走到常磐市 | map = 常磐市 |
| 在中心存档后出门走到 1 号道路 | 存档标志 + map = 1 号道路 |
| 击败一只野生宝可梦并在商店卖掉一个道具 | 经验值增加 且 钱增加 |

L3 需要新起点存档：从 `experiment/experiment_states/` 现有存档里挑，或用 `pack` 的来源 `.state` 现采。新判据所需的 RAM 探针（队伍数、经验值、存档标志）如果 `RamReadout` 里没有，就记为 world 侧前置改动，另开一条。

### E7 冻结 agent v2

- `v2/`：`samples.jsonl`（L1 20 + 勾选的 L2 / L3，带 `tier`、`oracle`）、`rubric.json`（只剩红线，见 E8）、`archives/`（`pack --version v2` 产出）、`coverage.md`（类别 × tier 表）。
- task 缺省版本改 `v2`；metadata 带 `tier`，`e2e_scorer` 按 `tier` 分组。
- **验收**（用户跑）：`validate.py --version v2` 全部通过。同步 `docs/spec/evals/SPEC.md` 的 agent 段。

### E8 清死字段（先量消费者）

按"删既有契约前先量消费者"三问逐个核对，三条都空才删：

| 对象 | 处理 |
|---|---|
| `EvalSample.rubric` / `RubricItem` / `RubricLevel` | v2 schema 删除；`Rubric` 只留 `red_lines`。v1 loader 读到这些字段时忽略 |
| `EvalSample.k_metric` | 删除（k 由 `--epochs` 决定，不属于样本） |
| `scorers/agent_goal_run/metric.py` | 量消费者；只剩测试在用就连测试一起删 |
| `scorers/agent_goal_run/score.py` 的 `Score` | 仍被 `mechanical_scorer` / `red_line_scorer` 使用，**保留**；只改掉"R5 后退役"之类过期的 docstring |

---

## G —— 基线与报告

| # | 内容 | 前置 | 谁跑 |
|---|---|---|---|
| G1 | v1 全 20 条 k=1，带归因与诊断列，记录公开 API/代码版本 | E1–E3、P0 阻塞排除；W6 后核接线 | 用户 |
| G2 | **成本闸**：用 G1 的每条平均成本 × v2 条数 × 3 估全量，报给用户确认预算 | G1、E7 | — |
| G3 | v2 全量 k=3：`--epochs 3`；L3 单独 `-T split=test` 跑 | G2 通过 | 用户 |
| G4 | 报告 `docs/experiments/10xx-agent-v2-baseline.md`：分 tier 的 pass@1 / pass^3、红线命中率、`failure_class` 分布、机械与模型的一致率、每条成本；失败样本附 Inspect View 定位方式 | G3 | 代码侧整理 |
| G5 | （可选）记忆对照：v2 val 上 `-T knowledge=false` 再跑 k=3，与 G3 对比 | G3 | 用户 |

G1 的报告可以先在归因结果上做第一轮系统改进；但 L3（test）**只在 G3 / G5 跑**，不用来调 prompt。

---

## 风险

| 风险 | 应对 |
|---|---|
| 存档因 `state_schema_hash` 变化被拒载 | P0 先发现；`pack` 重打。之后每次改 RunState 都要重打，在 CHANGELOG 影响面里写明 |
| 干扰用例的随机遇怪不可复现 | 只收在固定存档 + 按键下确定发生的；W4 的 epochs 2 兜底 |
| 装配点不能注入 brain | E4 闸门，退到备选方案 |
| L2 / L3 判据缺 RAM 探针 | 记为 world 侧前置改动，单独一条 CHANGELOG |
| 成本超预算 | G2 成本闸；可以先只跑 L1 + L2 |
| 合并名字时丢掉不同业务规则，或旧用例只验证内部步骤 | W6 分入口验回合/效果/退出边界；W3 逐条迁移和加强独立真值，历史结果不抵充新契约验收 |

---

## 实测记录

### P0 —— 2026-10-08 本机现状核验

使用仓库 `.venv/Scripts/python.exe`，日期按 Europe/Berlin。未改生产代码、样本定义或评分规则，未进入 W / E 实施。

| 项目 | 结论 | Inspect 墙钟 | 输入 / 输出 token | 模型调用 |
|---|---|---|---|---|
| world 全量 106 条 | 105/106；仅 `takeover:switch_from_party_list` 失败，`battle_switch` 3/4 | 22 秒 | 0 / 0 | 0 |
| `knowledge_door_transition` | `invalid`：旧存档状态结构不同；两评分列均 NOANSWER，`judged_count=0` | 1 秒 | 0 / 0 | 0 |
| `knowledge_shop_open_buy_menu` | 同上，尚不能判断旧停摆是否仍在 | 1 秒 | 0 / 0 | 0 |

墙钟取 `.eval` 的 `stats.started_at` / `completed_at`，不含 Python / Inspect 启动耗时。两条 agent 在恢复校验阶段退出，没有真实执行或模型回放；这些数字**不能用于 G2 成本估算**。Inspect 的整体 `status=success` 只表示测评流程结束，不代表 agent 样本有效。

**world 失败细节**：报告为 `unknown_script`，`data.status=rejected`，原因是 `battle_switch 场合没有脚本 battle_switch`；末态仍为 `battle_switch`，光标 `BULBASAUR`，期望在场 PIDGEY 与行动菜单均未满足。W2 应先核对场合到脚本的派发注册。

**重打结果与阻塞**：

1. `.env` 配了 `MCP_MEMORY_SERVER_URL=http://127.0.0.1:8766`，首次 pack 因服务未启动失败，随后打印 ✗ 又触发 GBK `UnicodeEncodeError`。
2. 设置 `PYTHONUTF8=1`，临时启动 memory MCP（根 `eval_results/p0_memory`，不使用日常记忆根），再次全量 pack：20/20 均报 `打包没有落下 checkpoint_save`，未生成新版存档。
3. 用公开 `harness.run(..., checkpoint_only=True)` 独立诊断并保留 trace：`checkpoint_error` 的 `stage=memory`，错误为 `AttributeError: 'MemoryMcpTool' object has no attribute 'snapshot'`。`Checkpointer.save()` 捕获该错误后返回 None，所以 pack 最后只能报缺 `checkpoint_save`。

**P0 尚未通过**：先修 memory MCP 与 checkpoint 快照契约的衔接，再重打 20 条并重跑 door / shop，才能得到真实 token、墙钟与回放证据。本轮没有通过清空 MCP 地址切换到进程内实现来绕过当前部署链路。

**证据路径**（仓库相对路径）：

- world：`eval_results/world_script_execute/2026-10-08T04-08-45-00-00_world-script-execute_dvxrwWvrncr7qgL3pNzeY7.eval`
- door：`eval_results/agent_goal_run/2026-10-08T04-09-22-00-00_agent-goal-run_Cq29uRQyevKGvcp8ZVmPJm.eval`；首次未传 `-T log_dir`，run 记录在 `eval_results/inspect/runs/knowledge_door_transition/run.json`
- shop：`eval_results/agent_goal_run/2026-10-08T04-11-30-00-00_agent-goal-run_XGng9f2sV8Y9NQUNECUBhw.eval`；run 记录在 `eval_results/agent_goal_run/runs/knowledge_shop_open_buy_menu/run.json`
- checkpoint 诊断：`eval_results/p0_checkpoint_probe/trace/01a119b5-572a-7979-b268-7f061e95a63e.json`

日志文件名为 UTC 时间（本机 Europe/Berlin 为 06:08–06:11）。Windows 下 Inspect control surface 因缺 `socket.AF_UNIX` 未启动，测评本身正常落 `.eval`。

### 2026-10-08 —— world 实施与复验

本轮只执行 world，不运行 agent_goal_run，不调用模型，不推进需要勾选的 v2 冻结。
现有 Windows venv/ROM 可用，Codex 已直接运行下列 world 步骤；上面的 agent P0 阻塞记录保持不变。

| 步骤 | 实测结果 | 产物 |
|---|---|---|
| P0 world 复核 | 105/106，仅 switch_from_party_list 失败；Inspect 总耗时 22 秒；模型调用/输入输出 token 均 0 | eval_results/world_p0_1008/*.eval |
| W1 | 分类兼容与覆盖工具落地；v1 覆盖不足，按约定退出 1；发现三个 C1 缺口；kind 指标用独立注册名避免 grouped 覆盖 | docs/eval/world-v2-coverage.md |
| W2 组验证 | battle_switch 四条 ×2 全过；Inspect 总耗时 2 秒；模型调用/token 0 | eval_results/world_switch_1008/*.eval |
| W2 最终全量 | v1 106 条 ×2 = 212/212，sample error 0，code/truth/pass 均 1.0，无 flaky；Inspect 总耗时 45 秒；模型调用/token 0；kind 两组均 1.0 | eval_results/world_v1_final_1008/*.eval |
| W3 预备 | 8 条输入拒绝/等待候选各两轮通过；circle/bounce 干扰两轮 RAM 核实；另两条草丛路径未触发干扰，如实排除 | docs/eval/world-v2-cases-draft.md；eval_results/world_candidates_1008/ |
| 本地验证 | evals/脚本相关 260 个测试通过；Ruff check/format 全仓通过；world 自持 A/B/C 全过 | 测试临时目录留本地 |

W4 尚未开始。后续新增场景、额外快照及保守登记出口的可达性处理见 W3 草稿。

### 2026-10-08 —— 公开能力收敛定案（文档更新）

用户确认 spec §2.1 的 31 项公开操作及简要流程，要求内部脚本由 world 实现、不对外暴露。
本次仅更新 spec/plan，新增 W5/W6 先于 W3/W4；既有 W1/W2 验收与 agent P0 阻塞记录保持。
world-v2-cases-draft.md / world-v2-coverage.md 标记为旧实现口径证据，待 W3 按公开契约重新生成。
未修改生产代码、冻结数据或实际调用入口，未新增模拟器/模型运行。
