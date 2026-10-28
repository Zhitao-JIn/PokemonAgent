# spec —— 中期评测数据集 v20261028_mid（M1–M5）

> 流程位置：intent（`docs/eval/mid_tasks/intent.md`，含 2026-10-28 的核实结果）→ **spec** → plan → 落码
> 前置：迁移（667–678）已合并；冻结机制与 `tier=mid` 已在 main（`SampleGoal`、`validate_tiers`、`run_arguments`）。判稳 WS1（680）不挡本任务，但合入后需复核战斗与治疗段的 oracle 步数。
> 编号：683（数据集）、684（机械判据）。

## 一、目标

产出新数据集版本 `v20261028_mid`：5 条中期样本，每条冻结 episode 目标表（`tier="mid"`，`goals` 各自不带 task），起点、派生存档、预算、起点预检、机械判据、知识条目齐全。父版本 `v20261021_retest5` 与已有 20 条短期样本、`v20261028_short_frozen` 不动。

## 二、决定表

| 编号 | 决定 |
|---|---|
| D1 | 目录 `evals/agent_short_goal_run/dataset/v20261028_mid/`；已存在则报错，不覆盖。构建脚本 `dataset/build/mid_dataset.py` 加数据文件 `dataset/build/mid_goals.json`（把本文第三节目标表原样写成数据，字节固定）。输出确定，重复生成 `samples.jsonl` 的 sha256 不变 |
| D2 | 样本 5 条，`sample_id`：`mid_walk_to_pallet`、`mid_heal_buy_return`、`mid_catch_then_heal`、`mid_customers_hint_buy`、`mid_cure_poison_budget`；`granularity="run"`、`tier="mid"`；样本的目标文 = 本文第三节"run 目标"；`goals` = 第三节目标表（每条 `goal`、判据文、`max_steps` = 建议 task 数，不带 `tasks`）；`check_id` 为第三节对应的新 id |
| D3 | 起点：M1、M4 用原存档原样（`knowledge_pokemon_center_enter`、`knowledge_shop_interaction`）；M2、M3、M5 为派生存档（第四节）。新目录 `states/` 只放本版本用到的存档（原样的两份加派生的三份），每个文件记 sha256 |
| D4 | 派生由 `dataset/build/mid_starts.py` 在独立模拟器里读原存档、改指定 RAM、另存（沿用 `injured_start.py` 的写法，目标已存在则拒绝覆盖）；`revision.json` 记每个文件的来源存档 sha256、被改地址与改前改后值、派生存档 sha256 |
| D5 | 预算：样本 `max_steps`（run 动作预算）= ⌈3 × oracle_steps ÷ 10⌉ × 10；M1 取遇敌最多的 98 步：300；M2 83：250；M3 61：190；M4 108：330；M5 76：230。目标表里的 `max_steps`（建议 task 数）按第三节 |
| D6 | `oracle_steps` 写进 `revision.json` 的每样本记录（不扩展 `EvalSample` 的字段；若 schema 里已有现成字段则用，没有就不加）。M1 另记无遇敌 6、中位 22、最大 98 与遇敌率 60% |
| D7 | 起点预检：`dataset/build/preconditions.py` 为每个新 `check_id` 加起点预检（见第五节），并导出一个常量 `PREFLIGHT_CHECK_IDS`（现有的 `party_healed`、`shop_cancelled` 加五个新 id）；评测入口 `solver/runner/one.py` 现在用写死的两元素集合决定哪些样本执行 reset、感知与 `validate_start`，**改为使用这个常量**（行为对旧两个 id 不变）。预检在评测运行时执行（要起模拟器），不在 `loader.check` 里；构建时由构建脚本另外用同一个函数对 5 个起点各验一次 |
| D8 | `rubric.json` 原样复制父版本；`coverage.md` 新写：每样本一行（sample_id、tier、episode 数、check_id、起点文件、oracle_steps、预算） |
| D9 | **知识库新增一条**（只服务 M1）：新建一份知识源与对应原子，机制与现有 12 条一致（先 `git grep -n "items_and_pickups.md"` 看现有原子怎么由源文件生成、`metadata.source` 与 `topic` 怎么取）。主题 `map_connections`，正文见第六节，逐字使用。`index.json`、`vectors.jsonl` 是被忽略的派生缓存，不提交 |
| D10 | 机械判据（684）：五个新 `check_id` 的规则放 `scorer/rules/`，沿用现有规则的结构与"每条规则至少一个正例一个反例"的测试约定（`tests/evals/agent_short_goal_run/test_evals_checks.py` 的现有约束）；判据读逐键观察序列，逻辑以 intent 第五节各任务的"机械判据"为准，取值以第三节为准 |
| D11 | 测试：全部用合成数据，不读真实数据集内容并断言；真实数据的核对只在生成后做一次（第七节），不写成常驻测试 |
| D12 | 本任务**允许启动模拟器**（只用于生成派生存档与起点预检）；不调用真实模型；不改 `pokemon_agent/`；不改父版本与其他数据集版本 |

## 三、目标表与 run 目标（逐字使用）

| 样本 | run 目标 | check_id | 序号 | episode 目标 | 给 judge 的判据 | 建议 task 数 |
|---|---|---|---|---|---|---:|
| M1 | 走到真新镇，再走进大木研究所。 | `walk_to_pallet` | g1 | 离开常青市，到达 1 号道路 | 人已到 1 号道路（地图 12） | 4 |
| | | | g2 | 沿 1 号道路走到真新镇 | 人已到达真新镇（地图 0） | 12 |
| | | | g3 | 走进大木研究所 | 人已进入大木研究所（地图 40） | 6 |
| M2 | 先去宝可梦中心把队伍治好，再去商店买 2 个精灵球，最后回到你现在站的这个位置。 | `heal_buy_return` | g1 | 去宝可梦中心把队伍治好 | 队伍每只都满血 | 6 |
| | | | g2 | 去商店买 2 个精灵球 | 精灵球比开始多 2 个、钱少 400 | 6 |
| | | | g3 | 回到你开始时站的那个格子 | 人站在开始时的格子上 | 6 |
| M3 | 把眼前这只野生宝可梦抓住，然后把整支队伍（包括它）治到满血。 | `catch_then_heal` | g1 | 把眼前这只野生宝可梦抓住 | 队伍多了一只，战斗已结束，没有停在起名界面 | 8 |
| | | | g2 | 把整支队伍（包括它）治到满血 | 队伍每只都满血，且治疗发生在抓到之后 | 6 |
| M4 | 先问问商店里的两位顾客，再去宝可梦中心把队伍治好，最后回商店买 1 件其中一位顾客提到过、店里又确实在卖的东西。 | `customer_hint_purchase` | g1 | 问商店里的两位顾客，听他们各说了什么 | 两位不同的顾客都说过话 | 6 |
| | | | g2 | 去宝可梦中心把队伍治好 | 队伍每只都满血 | 6 |
| | | | g3 | 回商店买 1 件被顾客提到过、店里又确实在卖的东西 | 买的是被提到且在售的那件，钱与背包只有这一笔变化 | 6 |
| M5 | 队伍里有宝可梦中毒了。不要去宝可梦中心，用别的办法把它治好，总共花的钱不超过 150。 | `cure_poison_budget` | g1 | 不进宝可梦中心，去商店买一件能治中毒的药，总共花的钱不超过 150 | 买了药，花费不超过 150，没进过宝可梦中心 | 6 |
| | | | g2 | 不进宝可梦中心，用它把中毒的宝可梦治好 | 中毒的宝可梦恢复正常，没进过宝可梦中心 | 6 |

## 四、派生存档

| 样本 | 源存档 | 改动 | 校验 |
|---|---|---|---|
| M2 | `knowledge_pokemon_center_enter.state` | `0xD16D`：`0x19→0x0C`（首只 HP 25→12） | 实验里的派生存档 sha256 为 `b3a58c3b4e673d24c8a72aed561cad4e0a3d8916bf781912068ed45dc78981fd`；本任务生成后应一致，不一致则如实报告差异 |
| M5 | `knowledge_pokemon_center_enter.state` | `0xD19B`：`0x00→0x08`（第二只状态字节，PSN） | 实验 sha256 `57d61ce0d06f04ed8c1c0393ab12c8504c98ba69c449a8d1b702fe0362c8e934`，要求同上 |
| M3 | `knowledge_catch_weaken_target.state` | `0xD16D`：`0x19→0x0C`，**并且把战斗里缓存的己方出战宝可梦 HP 同步改为 12**（`wBattleMonHP`，大端两字节，pokered 中位于 `0xD015`、`0xD016`；以实际读数为准，改前改后都要读出来记录） | 实验里的 M3 派生存档只改了队伍 HP，战斗画面仍显示 25/25，本任务要修正。生成后加载，解码战斗画面的己方 HP 行必须是 12/25；否则停下汇报 |

## 五、起点预检（`preconditions.py`）

运行时预检只能用 `validate_start(sample, ram, observation)` 拿到的东西（`RamReadout` 与 `TaskObservation`：场景、地图、队伍、钱、背包、是否在战斗、状态）。需要直接读内存的检查（例如事件位 `D74E`）只在构建时由构建脚本做，不进运行时预检。

- `walk_to_pallet`：地图 1 且在行走场景、不在战斗；队伍两只、全员存活。
- `heal_buy_return`：地图 1 且在行走场景；首只 HP 低于最大；球与钱等于起点值（球 4、钱 2000）。
- `catch_then_heal`：在战斗中；对手为野生；己方出战宝可梦 HP 低于最大（队伍读数与战斗缓存读数一致）；背包有精灵球。
- `customer_hint_purchase`：地图 42；钱 3000；背包无 item 70。构建时另验 `D74E` bit1 为 1（包裹这一幕已过去，进店不触发托付），此项不进运行时预检。
- `cure_poison_budget`：地图 1；第二只状态为 PSN；钱 2000；背包有 POTION。

## 六、知识条目正文（逐字）

```
## 关东地图连接：常青市、1 号道路与真新镇

- 常青市（地图 1）的南面出口通向 1 号道路（地图 12）。
- 1 号道路是一条南北向的长路，向南走到头就是真新镇（地图 0）。路上有草丛，在草丛里走动会遇到野生宝可梦；遇敌后可以战斗，也可以在战斗菜单里选 RUN 逃跑，逃掉后回到路上。路中间有一段被墙挡住，要从旁边绕过去。
- 真新镇有三栋房子：北边一排有两栋住宅，较南、位于中间偏东的那栋大房子是大木研究所（地图 40）。走到门口那一格就会进去。
```

## 七、生成后核对（构建步骤的核对，不写成常驻测试）

1. 5 条样本逐字段核对：`tier`、`goals`、`check_id`、`max_steps`、起点文件、与第二、三节一致；`goals[i]` 都不带 `tasks`。
2. 起点文件 sha256 与 `revision.json` 一致；M2、M5 与第四节给出的实验值比对；M3 的己方 HP 行为 12/25。
3. `loader.load` 得 5 条；`validate_tiers` 与 `loader.check` 通过（含起点预检）；`run_arguments` 对 5 条都给出冻结的目标表且两个冻结开关按 mid 档设置（`tests/evals/agent_short_goal_run/test_tier_runner.py` 里 mid 档的期望是依据）。
4. 重复运行 `samples.jsonl` sha256 不变；知识条目生成后，现有关于知识库的测试仍全部通过。

## 八、验收（683）

- 起点先取全量 pytest 基线（带 `--deselect tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome`，解释器用 `D:\Users\GummiGu\PycharmProjects\Pokemon_Agent\.venv\Scripts\python.exe`，junit 用 Python 的 re 读 `<testsuite ` 一行，读完删临时文件）；预期基线 tests=2885（若 WS1 已合入则以合入后的数为准）、failures=0、errors=0、skipped=72；最终 failures、errors 为 0，skipped 与基线相同。
- 守卫 `scripts/check_prompt_boundary.py --root .` 四条 `[ OK ]`；ruff 三项全绿；两种 `git diff --stat` 逐行一致；`CHANGELOG.md` 顶部新增 683 条目（五段，数字只写亲眼读到的）。
- 汇报"与指示有出入处"必须如实列出：任何改过的已有测试断言、任何范围外的文件、模拟器用法。

## 九、不做

不改 `pokemon_agent/`；不改父版本、`v20261028_short_frozen` 与其他版本；不调用真实模型；不为凑长改任务；不写读取真实数据集内容并断言的常驻测试；684（机械判据）在 683 验收后另行放行。

## 十、684：五个机械判据（规则）

> 前置：683 已合入（`v20261028_mid` 与 `PREFLIGHT_CHECK_IDS` 已在 main）。本节只加评分规则与它们的测试，不改数据集、不改 `pokemon_agent/`。

### 10.1 约定

1. 规则放 `evals/agent_short_goal_run/scorer/rules/` 下，导入即登记（沿用 `@rule("<check_id>")`、`CheckVerdict`、`utils.passed/failed/unjudgeable/first_match/target_frames/with_ram` 的写法；先读 `rules/center.py`、`rules/shop.py`、`rules/catch.py`、`rules/movement.py`、`scorer/npc_interactions.py`、`scorer/action_observations.py` 看现有判据怎么读帧、怎么读脚本内逐键观察）。新增模块可以按主题拆（例如 `rules/walk.py`、`rules/mid.py`），并在 `rules/__init__.py` 里导入。
2. 取证据的口径：run 粒度，整条执行线上的全部帧（`target_frames`）；内存读数（`ram`：队伍、背包、钱、是否在战斗、状态）永远可信；对话文字只认屏幕解码（`Frame.text` 或逐键观察里的 `dialog_text`），不认视觉；位置与地图来自内存。"第 i 帧先后"用账本时间序判。
3. 物品编号不要硬写：用 `pokemon_agent.world.items` 里的 `item_id(名字)`（`tests/world/test_items.py` 有用法）。精灵球 `POKé BALL`、`POTION`、`ANTIDOTE`、`PARLYZ HEAL`、`BURN HEAL`，包裹是 item 70。
4. 结论三态：`pass`、`fail`、`unjudgeable`（账不够判，包括开局条件不满足）。失败要写清是哪一类（reason 文字），证据放 `evidence`（帧 uuid）。
5. 每条规则至少一个正例、一个反例，按现有约定登记（`tests/evals/agent_short_goal_run/test_evals_checks.py` 的"每条已登记规则有正反例"与"配置的数据集所有 check_id 都已登记且有正反例"两个现有约束必须继续通过；先读该文件，照它的登记方式给五条规则各加一对）。再写合成账本测试覆盖各失败分支，全用合成数据，不读真实数据集内容并断言。

### 10.2 五条规则（`check_id` 与逻辑）

**`walk_to_pallet`**：起点帧 `map_id != 1` → unjudgeable；存在帧 i1 `map_id == 12`；存在帧 i2 晚于 i1 且 `map_id == 0`；存在帧 i3 晚于 i2 且 `map_id == 40`；终局不在战斗、无选项。失败分类：从未到 1 号道路 / 到了 12 没到 0 / 到了 0 没到 40 / 到了 40 但终局在战斗或停在选项里。reason 里附遇敌次数与战斗内帧数（统计即可，不进门槛）。

**`heal_buy_return`**：起点没有受伤队员（任何一只 `0 < hp < max_hp` 都不成立）→ unjudgeable；存在帧 i_heal：`map_id == 41` 且全员满血；终局球 = 起点 + 2、钱 = 起点 − 400、除 item 70 外背包其余物品数量不变；购买成交帧 i_buy（球数首次等于起点 + 2 的帧）晚于 i_heal；终局 `(map_id, x, y)` 等于起点的 `(map_id, x, y)` 且不在战斗。失败分类：从未满血 / 没买到 2 球或花费不对 / 先买后治 / 没回到起点 / 背包有别的变化。

**`catch_then_heal`**：终局队伍人数 = 起点 + 1；捕获帧 i_catch = 队伍人数首次等于起点 + 1 的带内存读数的帧（以内存为真值，**不要求**账里留有 `was caught` 台词：投球脚本会自动推进，模型调用之间的观察可能直接到捕获后的起名阶段，台词常常没被保存；若同一帧或更早的帧解码出 `was caught` 成功台词，可作为附加证据写进 evidence，但不是门槛）；存在治疗帧 i_heal 晚于捕获帧，`map_id == 41` 且全员满血；终局不在战斗、无选项、无起名键盘；对手 HP 从未为 0。失败分类：没抓到 / 抓到后没治好 / 先治后抓 / 终局停在起名或选项界面 / 把对手打倒了。

**`customer_hint_purchase`**：解码文字（含脚本内逐键观察的 `dialog_text`，读法参照 `npc_interactions.py`）中先后出现两句台词：`This shop sells many ANTIDOTEs.` 与 `No! POTIONs are all sold out.`（容忍换行与大小写差异，不容忍缺词），记两句各自首次出现的位置 iA、iB；存在治疗帧 i_heal：`map_id == 41` 且全员满血；终局相对起点 `ANTIDOTE` +1、钱 −100，`POKé BALL`、`PARLYZ HEAL`、`BURN HEAL` 数量不变（不计 item 70）；购买成交帧 i_buy（ANTIDOTE 数量首次比起点多 1 的帧）；顺序 max(iA, iB) < i_heal < i_buy。失败分类：缺一句台词 / 没治好 / 买错东西或多买 / 钱不对 / 顺序不对。

**`cure_poison_budget`**：起点第二只状态不是 PSN → unjudgeable；终局该只状态为 `ok`；全程没有进过地图 41：既没有任何带内存读数的帧 `map_id == 41`，脚本内逐键观察（读法同 `customer_hint_purchase` 取对话的方式，取观察里的 `place.map_id`）里也没有 41，防止一次脚本调用进出中心而被漏掉；起点钱 − 终局钱 ∈ [100, 150]；钱首次减少的帧早于该只状态变 ok 的帧。失败分类：没治好 / 进过中心 / 花费不在区间 / 先治后花钱（状态变好早于花钱，视为不是靠买药治好）。

### 10.3 验收（684）

- 起点先取基线（`tests=2920` 为 main 在 683 合入后的数，以实测为准）；最终 failures=0、errors=0、skipped=72；守卫四条 `[ OK ]`；ruff 三项；两种 `git diff --stat` 逐行一致；`CHANGELOG.md` 顶部新增 684 条目。
- 汇报里列：每条规则的正反例与覆盖的失败分支；改过的已有测试断言（预期没有）；如发现 `_ball_result` 之类的现有函数需要重构才能复用，说明做了什么、有没有改变原行为（现有测试必须仍过）。
- 允许范围：`evals/agent_short_goal_run/scorer/rules/` 下的新增与 `rules/catch.py` 的最小重构（对外复用的函数用公开名字，不要把带下划线的私有名放进 `__all__`）、`rules/__init__.py`、`scorer/utils.py`（只许加小工具）、新增与登记正反例所需的测试文件及 `test_evals_checks.py`（只许追加）、`CHANGELOG.md`。不改数据集、`pokemon_agent/`、`docs/`。不启动模拟器，不调用真实模型。
