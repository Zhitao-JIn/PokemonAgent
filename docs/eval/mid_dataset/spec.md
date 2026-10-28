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
| D7 | 起点预检：`dataset/build/preconditions.py` 为每个新 `check_id` 加起点预检（见第五节），预检不过的样本在 `loader.check` 阶段报错 |
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

- `walk_to_pallet`：地图 1 且在行走场景、不在战斗；队伍两只、全员存活。
- `heal_buy_return`：地图 1 且在行走场景；首只 HP 低于最大；球与钱等于起点值（球 4、钱 2000）。
- `catch_then_heal`：在战斗中；对手为野生；己方出战宝可梦 HP 低于最大（队伍读数与战斗缓存读数一致）；背包有精灵球。
- `customer_hint_purchase`：地图 42；钱 3000；背包无 item 70；`D74E` bit1 为 1（包裹这一幕已过去，进店不触发托付）。
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
